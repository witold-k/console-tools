- please got to repo https://github.com/witold-k/buildscripts and examine
 lua/bin/xcat.lua

 - i need simular functionality as rust application:

 - additionally i need a config file, like in agagens with same file suffixes.
 - also auto creation if not availabe

 - some base library function (xcat should use them):
   - function to copy to system clipboard, for x, wayland and windows
   - use https://github.com/witold-k/fsscanner to scan files
   - scanning should always use filter from config
   - xcat without arguments : scan current dir with filter and copy to clipboard
   - xcat -d <dir> scan dir <dir> and copy to clipboard
   - xcat -e <file> [-d dir] [ -- args for excuted file ] scan dir, copy to clipboard execute file and copy stdout + stderr to clipboard
        - in case file is pure executable => just execuete file
        - Justfile call just file
        - Makefile/makefile => call make file
        - *.sh call bash
        - *.ps1 call powershell
    - xcat -h also offer detailed help with some examples

    - -r standalone (searched for exe)

    - also provide excutable jvm build.

