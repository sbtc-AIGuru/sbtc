# Python text processor

The `processor` CPython extension exposes the existing C++ `Processor` class.
It requires a C++17 compiler, Python development headers, and setuptools.
The Python-only build does not require `nlohmann_json`.

## Build and use without installing

Run from this directory:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
python setup.py build_ext --inplace
python -m unittest discover -s tests -v
```

The resulting extension can be imported while this directory is on `sys.path`:

```python
from processor import Processor

processor = Processor()
text = processor.clean_text("xin chào! Nội  dung.")
print(text)  # Nội dung.
```

`Processor()` takes no arguments. `clean_text(text: str) -> str` accepts a
positional or keyword argument and returns a new string without changing its
input. Other input types raise `TypeError`.

## Install into the active environment

When installation is desired, run from this directory:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
python -m pip install --no-build-isolation --no-deps .
```

## Build with CMake

CMake 3.18 or newer can build the extension directly:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_PREPROCESS_EXECUTABLE=OFF \
    -DPython3_EXECUTABLE="$(command -v python)"
cmake --build build
PYTHONPATH="$PWD/build" python -m unittest discover -s tests -v
```

By default CMake also builds the original `preprocess` executable, which requires
`nlohmann_json`. Use `-DBUILD_PYTHON_MODULE=OFF` for an executable-only build.

## Existing algorithm limits

The binding preserves the C++ pipeline: remove a greeting sentence, replace
U+FFFD, collapse consecutive ASCII spaces, then remove HTML tags. Greeting
matching uses substrings and byte-based case conversion, not Unicode case
folding. Tabs and newlines are not normalized; HTML removal can leave extra or
trailing spaces. This is a text cleanup helper, not an HTML parser.

Build the extension again after changing Python versions or C++ sources.
