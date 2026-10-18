"""Exercise scoring, token budgets and real Qwen forward with tiny random weights."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch
import transformers

from BackEnd.app.Retrieval import qwen_reranker as qwen


class Tokenizer:
    def encode(self, text, **options):
        assert options == {"add_special_tokens": False}
        return [ord(char) + 2 for char in text]

    def convert_tokens_to_ids(self, text):
        return {"no": 0, "yes": 1}[text]

    def pad(self, features, **options):
        rows = features["input_ids"]
        width = max(map(len, rows))
        return {"input_ids": torch.tensor([[0] * (width - len(row)) + row for row in rows]),
                "attention_mask": torch.tensor([[0] * (width - len(row)) + [1] * len(row) for row in rows])}


class Model:
    def __init__(self):
        self.calls = []

    def eval(self):
        return self

    def to(self, device):
        return self

    def __call__(self, **features):
        assert features.pop("use_cache") is False
        assert features.pop("logits_to_keep") == 1
        self.calls.append(features)
        inputs = features["input_ids"]
        logits = torch.zeros((len(inputs), 1, 2))
        logits[:, 0, 1] = (inputs == ord("Z") + 2).sum(dim=1).float()
        return SimpleNamespace(logits=logits)


@pytest.fixture
def loaders(monkeypatch):
    tokenizer, model = Tokenizer(), Model()
    token_loader, model_loader = Mock(return_value=tokenizer), Mock(return_value=model)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", token_loader)
    monkeypatch.setattr(transformers.AutoModelForCausalLM, "from_pretrained", model_loader)
    return tokenizer, model, token_loader, model_loader


def test_local_pinned_model_yes_no_scoring_and_padding(loaders):
    _, model, token_loader, model_loader = loaders
    reranker = qwen.QwenReranker(cache_dir="artifacts/model-cache", batch_size=3,
                                max_length=512, token_budget=1536)
    assert reranker.score("query", ["plain", "ZZ", "Z"]) == pytest.approx([
        0.5, torch.sigmoid(torch.tensor(2.)).item(), torch.sigmoid(torch.tensor(1.)).item(),
    ])
    assert len(model.calls) == 1
    mask = model.calls[0]["attention_mask"]
    assert mask[1, 0] == 0 and mask[:, -1].tolist() == [1, 1, 1]
    for loader in (token_loader, model_loader):
        assert loader.call_args.args == (qwen.MODEL_NAME,)
        assert loader.call_args.kwargs["revision"] == qwen.MODEL_REVISION
        assert loader.call_args.kwargs["local_files_only"] is True
        assert loader.call_args.kwargs["cache_dir"] == "artifacts/model-cache"
    assert token_loader.call_args.kwargs["padding_side"] == "left"
    assert model_loader.call_args.kwargs["dtype"] == torch.float32


def test_long_documents_keep_all_tokens_full_query_and_best_window(loaders):
    tokenizer, model, *_ = loaders
    reranker = qwen.QwenReranker(batch_size=8, max_length=512, token_budget=512)
    scores = reranker.score("full query", ["a" * 700 + "ZZZ", "plain"])
    assert scores == pytest.approx([torch.sigmoid(torch.tensor(3.)).item(), 0.5])
    assert len(model.calls) > 2
    prefix = tokenizer.encode(qwen.PREFIX + f"<Instruct>: {qwen.INSTRUCTION}\n<Query>: full query\n<Document>: ",
                              add_special_tokens=False)
    suffix = tokenizer.encode(qwen.SUFFIX, add_special_tokens=False)
    documents = []
    for call in model.calls:
        inputs = call["input_ids"]
        assert inputs.numel() <= 512
        for row, mask in zip(inputs, call["attention_mask"]):
            sequence = row[mask.bool()].tolist()
            assert sequence[:len(prefix)] == prefix
            assert sequence[-len(suffix):] == suffix
            documents.extend(sequence[len(prefix):-len(suffix)])
    assert documents == tokenizer.encode("a" * 700 + "ZZZplain", add_special_tokens=False)


def test_empty_long_query_invalid_budgets_and_nonfinite_scores(loaders, monkeypatch):
    _, model, *_ = loaders
    reranker = qwen.QwenReranker(max_length=512, token_budget=512)
    assert reranker.score("query", []) == []
    assert not model.calls
    with pytest.raises(ValueError, match="Query exceeds"):
        reranker.score("q" * 600, ["doc"])
    with pytest.raises(ValueError, match="nonempty"):
        reranker.score("", ["doc"])
    with pytest.raises(ValueError, match="token_budget"):
        qwen.QwenReranker(max_length=512, token_budget=511)
    monkeypatch.setattr(Model, "__call__", lambda self, **features:
                        SimpleNamespace(logits=torch.full((1, 1, 2), float("nan"))))
    with pytest.raises(ValueError, match="nonfinite"):
        reranker.score("query", ["doc"])


def test_real_qwen_forward_without_network_or_pretrained_weights(loaders):
    _, _, _, model_loader = loaders
    torch.manual_seed(5)
    model_loader.return_value = transformers.Qwen3ForCausalLM(transformers.Qwen3Config(
        vocab_size=256, hidden_size=16, intermediate_size=32, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=8, pad_token_id=0,
    ))
    reranker = qwen.QwenReranker(max_length=512, token_budget=1024)
    scores = reranker.score("query", ["short", "longer document"])
    assert len(scores) == 2 and all(0 <= score <= 1 for score in scores)
    assert scores == pytest.approx([reranker.score("query", [doc])[0]
                                   for doc in ("short", "longer document")], abs=1e-6)
