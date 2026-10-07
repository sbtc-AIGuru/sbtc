#include "src/processor.h"
#include <cctype>
#include <utility>
#include <algorithm>
#include <cctype>

Processor::Processor() {
    greeting_word = {
        // Vietnamese
        "xin chào",
        "chào bạn",
        "chào anh",
        "chào chị",
        "chào em",
        "chào mọi người",
        "chào các bạn",
        "kính chào",
        "chào buổi sáng",
        "chào buổi chiều",
        "chào buổi tối",

        // English
        "hello",
        "hi",
        "hey",
        "greetings",
        "good morning",
        "good afternoon",
        "good evening"
    };
}

std::string Processor::to_lower(std::string st) {
    std::transform(
        st.begin(),
        st.end(),
        st.begin(),
        [](unsigned char c) {
            return std::tolower(c);
        }
    );

    return st;
}

void Processor::remove_greeting_sentence(std::string &st) {
    if (st.empty())
        return;

    size_t sentence_end = st.find_first_of(".!?\n");

    std::string first_sentence;

    if (sentence_end == std::string::npos) {
        first_sentence = st;
    } else {
        first_sentence = st.substr(0, sentence_end + 1);
    }

    std::string lower_sentence = to_lower(first_sentence);

    bool has_greeting = false;

    for (const auto &word : greeting_word) {
        if (lower_sentence.find(word) != std::string::npos) {
            has_greeting = true;
            break;
        }
    }

    if (!has_greeting)
        return;

    if (sentence_end == std::string::npos) {
        st.clear();
        return;
    }

    st.erase(0, sentence_end + 1);

    // Xóa whitespace ở đầu
    size_t first_non_space = st.find_first_not_of(" \t\r\n");

    if (first_non_space == std::string::npos) {
        st.clear();
    } else {
        st.erase(0, first_non_space);
    }
}

/*
protected:
    void remove_greeting_sentence(std::string &st);
    void remove_unk_word(std::string &st); 
    void normalize_space(std::string &st);
    void remove_HTML_tag(std::string & st); 
    */

void Processor::remove_unk_word(std::string &st) {
    /*For example: std::string text = "Bệnh nh�n bị sốt.";
    remove_unk_word(text);
    cout >> text; -> Bệnh nh n bị sốt
*/
    const std::string replacement = "\xEF\xBF\xBD";

    size_t pos = 0;

    while ((pos = st.find(replacement, pos)) != std::string::npos) {
        st.replace(pos, replacement.size(), " ");
    }
}

void Processor::normalize_space(std::string & st) {
    std::string result = ""; 
    bool is_previous_space = false; 

    for (unsigned char c: st) {
        if (c != ' ') {
            result += c; 
            is_previous_space = false; 
        }
        else {
            if (!is_previous_space) {
                result += ' '; 
                is_previous_space = true; 
            }
        }
    }
    st = std::move(result);
}

void Processor::remove_HTML_tag(std::string &st) {
    std::string result;
    result.reserve(st.size());

    bool inside_tag = false;
    char quote = '\0';

    for (size_t i = 0; i < st.size(); ++i) {
        char c = st[i];

        if (!inside_tag) {
            if (c == '<' && i + 1 < st.size()) {
                char next = st[i + 1];
                if (std::isalpha(static_cast<unsigned char>(next)) ||
                    next == '/' ||
                    next == '!' ||
                    next == '?') {

                    inside_tag = true;

                    if (!result.empty() && result.back() != ' ')
                        result += ' ';

                    continue;
                }
            }

            result += c;
        }
        else {
            if (quote != '\0') {
                if (c == quote)
                    quote = '\0';

                continue;
            }

            if (c == '"' || c == '\'') {
                quote = c;
                continue;
            }
            if (c == '>') {
                inside_tag = false;
            }
        }
    }

    st = std::move(result);
}

void Processor::clean_text(std::string &st) {
    remove_greeting_sentence(st); 
    remove_unk_word(st); 
    normalize_space(st); 
    remove_HTML_tag(st);
}