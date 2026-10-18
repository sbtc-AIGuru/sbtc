"""Local Qwen3 yes/no relevance scoring; never generate or rewrite source text."""

import logging
import math

LOGGER = logging.getLogger(__name__)
MODEL_NAME = "Qwen/Qwen3-Reranker-0.6B"
MODEL_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
INSTRUCTION = "Given a medical search query, retrieve relevant passages that answer the query"
PREFIX = (
    '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
    'and the Instruct provided. Note that the answer can only be "yes" or "no".'
    '<|im_end|>\n<|im_start|>user\n'
)
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class QwenReranker:
    def __init__(self, *, device="cpu", batch_size=4, max_length=8192,
                 token_budget=8192, cache_dir=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if batch_size < 1 or not 1 <= max_length <= 32768 or token_budget < max_length:
            raise ValueError("Require batch_size > 0, max_length <= 32768 and token_budget >= max_length")
        self.batch_size, self.max_length, self.token_budget = batch_size, max_length, token_budget
        self.device = torch.device(device)
        options = {"revision": MODEL_REVISION, "local_files_only": True}
        if cache_dir:
            options["cache_dir"] = str(cache_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, padding_side="left", **options)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME, dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
            attn_implementation="sdpa", **options,
        ).eval().to(self.device)
        self.no_id = self.tokenizer.convert_tokens_to_ids("no")
        self.yes_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.suffix = self.tokenizer.encode(SUFFIX, add_special_tokens=False)

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Score every document, taking the best window for overlong documents.

        Keep the entire query in each window. Queries that leave no document
        context fail explicitly. Batch limits include padding, not just content.
        """
        import torch

        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a nonempty string")
        if not documents:
            return []
        prefix = self.tokenizer.encode(
            PREFIX + f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: ",
            add_special_tokens=False,
        )
        window_size = self.max_length - len(prefix) - len(self.suffix)
        if window_size < 1:
            raise ValueError("Query exceeds Qwen context; increase reranker_max_length (up to 32768)")
        scores = [-math.inf] * len(documents)
        batch, indices, longest = [], [], 0

        def flush():
            features = self.tokenizer.pad(
                {"input_ids": batch}, padding=True, return_tensors="pt",
            )
            features = {key: value.to(self.device) for key, value in features.items()}
            with torch.inference_mode():
                # Only the final position is needed; avoid sequence x vocabulary logits.
                logits = self.model(**features, use_cache=False, logits_to_keep=1).logits[:, -1, :]
                values = torch.softmax(logits[:, [self.no_id, self.yes_id]].float(), dim=-1)[:, 1]
            values = values.cpu().tolist()
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Qwen returned nonfinite relevance scores")
            for index, value in zip(indices, values, strict=True):
                scores[index] = max(scores[index], value)

        windows = 0
        for index, document in enumerate(documents):
            tokens = self.tokenizer.encode(document, add_special_tokens=False)
            for offset in range(0, max(1, len(tokens)), window_size):
                sequence = prefix + tokens[offset:offset + window_size] + self.suffix
                padded_length = max(longest, len(sequence))
                if batch and (len(batch) >= self.batch_size or
                              padded_length * (len(batch) + 1) > self.token_budget):
                    flush()
                    batch, indices, longest = [], [], 0
                batch.append(sequence)
                indices.append(index)
                longest = max(longest, len(sequence))
                windows += 1
        if batch:
            flush()
        LOGGER.info("Qwen scored %d chunks in %d windows", len(documents), windows)
        return scores
