#include <fstream>
#include <iostream>
#include <string>
#include <nlohmann/json.hpp>

using json = nlohmann::json; 

int main() {
    std::ifstream file("data.jsonl"); 
    if (!file.is_open()) {
        std::cerr << "Cannot open file\n"; 
        return 1; 
    }
    std::string line; 
    while(std::getline(file, line)) {
        if (line.empty()) {
            std::cout << "Empty line\n"; 
            continue;
        }

        try {
            json j = json::parse(line); 
            std::cout << "Ok\n"; 
        } catch (const json::parse_error& e){
            std::cerr << "Invalid JSON: " << e.what() << "\n"; 
        }
    }
    return 0;
}