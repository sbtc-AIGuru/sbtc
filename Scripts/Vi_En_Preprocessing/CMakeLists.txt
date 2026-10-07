cmake_minimum_required(VERSION 3.16)

project(preprocess)

set(CMAKE_CXX_STANDARD 17)

find_package(nlohmann_json REQUIRED)

add_executable(preprocess src/main.cpp)

target_link_libraries(preprocess PRIVATE nlohmann_json::nlohmann_json)