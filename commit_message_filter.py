import sys

def check_commit_message(msg) :
    (summary, _, rest) = msg.partition("\n")
    (sep, _, body) = rest.partition("\n")
    if sep != "" :
        return "The second line of the commit message must be empty."
    if len(summary) > 200 :
        return "The first line of the commit message is way too long."
    (context, colon, details) = summary.partition(": ")
    if colon == "" or len(context) > 32 :
        return "The first line of the commit message must start " + \
            "with a context terminated by a colon and a space, " + \
            "for example \"lavu/opt: \" or \"doc: \"."
    longlines = 0
    lines = 0
    for line in body.split("\n") :
        lines = lines + 1
        if len(line) <= 76 :
            continue
        spaces = 0
        nontext = 0
        probablecode = 0
        # Try to detect code lines, probably URLs too
        for c in line :
            if c == ' ' :
                spaces = spaces + 1
            if not ((c >= 'a' and c <= 'z') or
                    (c >= 'A' and c <= 'Z') or
                    (c >= '0' and c <= '9') or
                    c == ' ' or
                    c == '.' or
                    c == ',' or
                    c == ';' or
                    c == ':' or
                    c == '-' or
                    c == "'") :
                nontext = nontext + 1
            if c == '/' :
                probablecode = probablecode + 1
        if nontext > 8 or probablecode > 0 or spaces < 8 :
            continue
        longlines = longlines + 1
    if longlines > lines / 4 :
        return "Please wrap lines in the body of the commit message between 60 and 72 characters."

    return ""

if __name__ == "__main__":
    msg = sys.stdin.read()
    out = check_commit_message(msg)
    print(out)
