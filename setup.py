"""
Cython build configuration for Adaptora.

To compile the core modules:
    python setup.py build_ext --inplace

This creates .so (compiled) files that replace the .py files during import,
making the implementation non-readable while preserving the interface.
"""

from setuptools import setup, find_packages
from setuptools.extension import Extension
from Cython.Build import cythonize
import os

# Only compile these files if Cython is available
# (otherwise standard Python imports are used)
extensions = [
    Extension(
        name="app.services.dynamic_agent_service",
        sources=["app/services/dynamic_agent_service.py"],
        language="c",
    ),
    Extension(
        name="app.services.llm_provider",
        sources=["app/services/llm_provider.py"],
        language="c",
    ),
]

setup(
    name="adaptora",
    version="1.0.0",
    description="Dynamic API Agent with MCP server",
    author="Ayush Gupta",
    author_email="guptayush02@gmail.com",
    url="https://github.com/ayushgupta02/adaptora",
    packages=find_packages(),
    ext_modules=cythonize(extensions, language_level=3, compiler_directives={"binding": True}),
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.104",
        "uvicorn>=0.24",
        "sqlalchemy>=2.0",
        "pydantic>=2.0",
        "requests>=2.31",
        "redis>=5.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
    ],
)
