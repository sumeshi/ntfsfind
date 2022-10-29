#!/bin/sh

poetry config virtualenvs.in-project true
poetry install

echo 'Welcome to the ntfsfind development environment!'