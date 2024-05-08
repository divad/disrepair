# disrepair
Checks for out-of-date Python packages in requirements files, intended for use with pip-tools.

## Install

Run

```pip install disrepair```

## Usage

To list available updates, use:

```disrepair check path/to/requirements.in```

To interactively update packages in the file:

```disrepair update path/to/requirements.in```
