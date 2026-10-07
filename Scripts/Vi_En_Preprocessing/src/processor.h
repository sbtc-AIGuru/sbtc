#pragma once

#include <string>
#include <vector>

class Processor {
private:
    std::vector<std::string> greeting_word;

    std::string to_lower(std::string st);

protected:
    void remove_greeting_sentence(std::string &st);
    void remove_unk_word(std::string &st); 
    void normalize_space(std::string &st);
    void remove_HTML_tag(std::string & st); 
public:
    Processor();
    void clean_text(std::string &st);
};