cmake_minimum_required(VERSION 3.18)

project(preprocess LANGUAGES CXX)

option(BUILD_PREPROCESS_EXECUTABLE "Build the JSONL executable" ON)
option(BUILD_PYTHON_MODULE "Build the processor Python extension" ON)

add_library(processor_core STATIC
    src/processor.cpp
    src/processor.h
)
target_compile_features(processor_core PUBLIC cxx_std_17)
set_target_properties(processor_core PROPERTIES
    CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO
    POSITION_INDEPENDENT_CODE YES
)
target_include_directories(processor_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")

if(BUILD_PREPROCESS_EXECUTABLE)
    find_package(nlohmann_json CONFIG REQUIRED)
    add_executable(preprocess src/preprocessing.cpp)
    set_target_properties(preprocess PROPERTIES CXX_EXTENSIONS NO)
    target_link_libraries(preprocess PRIVATE processor_core nlohmann_json::nlohmann_json)
endif()

if(BUILD_PYTHON_MODULE)
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)
    Python3_add_library(processor MODULE WITH_SOABI src/python_bindings.cpp)
    set_target_properties(processor PROPERTIES CXX_EXTENSIONS NO)
    target_link_libraries(processor PRIVATE processor_core)
endif()
