#!/usr/bin/env python

from setuptools import setup
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md')) as f:
    long_description = f.read()

setup(
    name='oval',
    version='0.0.1',
    description='Oval is an overlap alignment search tool',
    long_description=long_description,
    url='https://github.com/amirkdv/oval',
    author='Amir Kadivar',
    author_email='amir@amirkdv.ca',
    #license='MIT',
    #keywords='sequence DNA overlap alignment fragment assembly',
    packages=['oval'],
    setup_requires=[
        'cffi',
        'biopython',
    ],
    install_requires=[
        'biopython',
        'termcolor',
        'cffi',
        'python-igraph',
        # 'pycairo', can't be done yet; see https://bugs.freedesktop.org/show_bug.cgi?id=58772
    ],
    extras_require={
        'DOCS': [
            'sphinx',
            'sphinx.ext.napoleon',
            'sphinx.rdt.theme',
            'sphinx.ext.mathjax',
            'breathe',
            'mock' # only used on rtfd.org to mock packages with binary dependencies
        ]
    }
)
