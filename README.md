# disrepair
Checks for out-of-date Python packages in requirements files

## Install

Run

```pip install disrepair```

## Usage

Pass the requirements file to disrepair:

```disrepair path/to/requirements.in```

There are several options:

```
  -v, --verbose           Show all package statuses
  -i, --info              Show likely package changelog/info links
  -b, --boring            Disable the rich text formatting
  -j, --json-repo TEXT    Repository URL for the JSON API
  -s, --simple-repo TEXT  Repository URL for the Simple API
  -S, --simple-only       Only use the Simple API to lookup versions
  -J, --json-only         Only use the JSON API to lookup versions
  -p, --pin-warn          Warn when a package version is not pinned
```