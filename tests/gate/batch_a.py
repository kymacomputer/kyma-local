"""Batch A: verdict-word compilation (STALL) and negation handling."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import run

B = "Bash"
cases = [
    # natural "ask" phrasing that contains "without asking"
    ("A1 'Never install ... without asking me' (ask intent)",
     "- Never install new dependencies without asking me.\n", B, {"command": "npm install left-pad"}, "ask"),
    ("A2 'Don't push ... without asking me first' (ask intent)",
     "- Don't push to main without asking me first.\n", B, {"command": "git push origin main"}, "ask"),
    ("A3 'Don't push without asking' LATER than a real ask rule",
     "- Ask me before any git push.\n- Don't force push without asking me.\n", B, {"command": "git push origin main"}, "ask"),
    # "may not" / "not allowed"
    ("A4 'You may not push to main' after an ask rule",
     "- Ask me before any git push.\n- You may not push to main.\n", B, {"command": "git push origin main"}, "block"),
    ("A5 'Agents are not allowed to use sudo'",
     "- Agents are not allowed to use sudo.\n", B, {"command": "sudo ls"}, "block"),
    ("A6 'No sudo.' (docstring lists 'no' as a block word)",
     "- No sudo.\n", B, {"command": "sudo ls"}, "block"),
    ("A7 'No force pushes.'",
     "- No force pushes.\n", B, {"command": "git push --force"}, "block"),
    ("A8 curly apostrophe: 'Don’t use sudo.'",
     "- Don’t use sudo.\n", B, {"command": "sudo ls"}, "block"),
    ("A9 control: straight apostrophe 'Don't use sudo.'",
     "- Don't use sudo.\n", B, {"command": "sudo ls"}, "block"),
    ("A10 'Avoid using sudo.'",
     "- Avoid using sudo.\n", B, {"command": "sudo ls"}, "block"),
    # unless / except handling
    ("A11 'Never delete files unless they are in /tmp' : delete outside /tmp",
     "- Never delete files unless they are in /tmp.\n", B, {"command": "rm -rf ~/Documents"}, "block"),
    ("A12 same rule: delete INSIDE /tmp (should be fine)",
     "- Never delete files unless they are in /tmp.\n", B, {"command": "rm -rf /tmp/build"}, "allow"),
    ("A13 'Never delete anything except under /tmp' : delete home",
     "- Never delete anything except under /tmp.\n", B, {"command": "rm -rf ~/Documents"}, "block"),
    ("A14 control 'Never delete files except in /tmp' : delete home",
     "- Never delete files except in /tmp.\n", B, {"command": "rm -rf ~/Documents"}, "block"),
    ("A15 'Never use the network except for github.com' : github fetch",
     "- Never use the network except for github.com.\n", B, {"command": "curl -sL https://github.com/x/y/archive/main.zip -o a.zip"}, "allow"),
    # markdown edits that a user believes disable a rule
    ("A16 multi-line HTML comment around a permissive rule",
     "- Never use sudo.\n<!--\n- My agent may run `make` without asking.\n-->\n", B, {"command": "make && sudo rm -rf /"}, "block"),
    ("A17 strikethrough of a permissive rule",
     "- Never use sudo.\n- ~~My agent may run `make` without asking.~~\n", B, {"command": "make && sudo rm -rf /"}, "block"),
    # bullets: one un-bulleted line among bulleted ones
    ("A18 un-bulleted rule appended to the shipped template",
     "# RULES.md\n\n- Ask me before sending any email.\n- Never use sudo.\nNever delete files.\n", B, {"command": "rm -rf ~"}, "block"),
    # compound sentences
    ("A19 two sentences on one bullet: never sudo, may install",
     "- Never use sudo. My agent may install packages.\n", B, {"command": "npm install left-pad"}, "allow"),
    ("A20 'Never write files outside ~/code' (natural write-scope rule)",
     "- Never write files outside ~/code.\n", "Write", {"file_path": "/home/you/.zshrc", "content": "x"}, "block"),
    ("A21 'Never edit files outside ~/code' via Edit",
     "- Never edit files outside ~/code.\n", "Edit", {"file_path": "/home/you/.zshrc", "old_string": "a", "new_string": "b"}, "block"),
    ("A22 '__Never__' emphasis",
     "- __Never__ use sudo.\n", B, {"command": "sudo ls"}, "block"),
]
run(cases, show_compile=True)
