"""Build the native processor extension using the existing C++ implementation."""

from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            name="processor",
            sources=["src/python_bindings.cpp", "src/processor.cpp"],
            include_dirs=["."],
            depends=["src/processor.h"],
            language="c++",
            extra_compile_args=["-std=c++17"],
        )
    ]
)
