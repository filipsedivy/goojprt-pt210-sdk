import sys, os
sys.path.insert(0, os.path.abspath(".."))

project = "goojprt-pt210-sdk"
author = "Filip Sedivy"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

html_theme = "alabaster"
