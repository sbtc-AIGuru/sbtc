#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <exception>
#include <new>
#include <string>

#include "src/processor.h"

namespace {

struct ProcessorObject {
    PyObject_HEAD
    Processor* processor;
};

void processor_dealloc(ProcessorObject* self) {
    delete self->processor;
    PyTypeObject* type = Py_TYPE(self);
    type->tp_free(reinterpret_cast<PyObject*>(self));
    Py_DECREF(type);
}

PyObject* processor_new(PyTypeObject* type, PyObject* args, PyObject* kwargs) {
    static char* keywords[] = {nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, ":Processor", keywords)) {
        return nullptr;
    }

    auto* self = reinterpret_cast<ProcessorObject*>(type->tp_alloc(type, 0));
    if (self == nullptr) {
        return nullptr;
    }
    self->processor = nullptr;
    try {
        self->processor = new Processor();
    } catch (const std::bad_alloc&) {
        Py_DECREF(reinterpret_cast<PyObject*>(self));
        return PyErr_NoMemory();
    } catch (const std::exception& error) {
        Py_DECREF(reinterpret_cast<PyObject*>(self));
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
    return reinterpret_cast<PyObject*>(self);
}

PyObject* processor_clean_text(ProcessorObject* self, PyObject* args, PyObject* kwargs) {
    static char text_keyword[] = "text";
    static char* keywords[] = {text_keyword, nullptr};
    PyObject* input = nullptr;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "U:clean_text", keywords, &input)) {
        return nullptr;
    }

    Py_ssize_t size = 0;
    const char* utf8 = PyUnicode_AsUTF8AndSize(input, &size);
    if (utf8 == nullptr) {
        return nullptr;
    }

    try {
        // Python strings are immutable; clean a separate UTF-8 buffer.
        std::string text(utf8, static_cast<std::size_t>(size));
        self->processor->clean_text(text);
        return PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "strict");
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
}

PyMethodDef processor_methods[] = {
    {"clean_text", reinterpret_cast<PyCFunction>(processor_clean_text),
     METH_VARARGS | METH_KEYWORDS,
     PyDoc_STR("clean_text(text: str) -> str\n\nReturn text cleaned by the C++ processor.")},
    {nullptr, nullptr, 0, nullptr},
};

PyType_Slot processor_slots[] = {
    {Py_tp_new, reinterpret_cast<void*>(processor_new)},
    {Py_tp_dealloc, reinterpret_cast<void*>(processor_dealloc)},
    {Py_tp_methods, processor_methods},
    {Py_tp_doc, const_cast<char*>("Vietnamese and English text processor.")},
    {0, nullptr},
};

PyType_Spec processor_spec = {
    "processor.Processor",
    static_cast<int>(sizeof(ProcessorObject)),
    0,
    Py_TPFLAGS_DEFAULT,
    processor_slots,
};

PyModuleDef processor_module = {
    PyModuleDef_HEAD_INIT,
    "processor",
    "Python bindings for the C++ text processor.",
    0,
    nullptr,
    nullptr,
    nullptr,
    nullptr,
    nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit_processor() {
    PyObject* module = PyModule_Create(&processor_module);
    if (module == nullptr) {
        return nullptr;
    }

    PyObject* type = PyType_FromSpec(&processor_spec);
    if (type == nullptr) {
        Py_DECREF(module);
        return nullptr;
    }
    if (PyModule_AddObject(module, "Processor", type) < 0) {
        Py_DECREF(type);
        Py_DECREF(module);
        return nullptr;
    }
    return module;
}
