"""Plan mode's read-only `bash` (#114): an allow-list of commands that look and change nothing.

In plan mode the model inspects the machine and proposes; nothing may change until the owner
approves the plan. "Read-only bash" cannot be proven, so this is an **allow-list** (decided in
#114), the inverse of the approval patterns: a command runs only if it is a simple command (no
shell syntax at all — see shellwords.py), its program is on the list, and its arguments pass that
program's check. Everything else is refused, and the model is told to put it in the plan.

- Programs are matched by bare name. A path (`/usr/bin/ls`, `./x.sh`) is never on the list.
- `sudo` (optionally `-n`) in front is allowed: reading root-only files is ordinary inspection.
- Programs with a writing sub-command or flag are listed with a check: `systemctl status` yes,
  `systemctl stop` no; `journalctl` yes, `journalctl --vacuum-size` no; `date` yes, `date -s` no.
- Left out on purpose: interpreters, `curl`/`wget` (can POST and write), `sed`/`awk`/`sort`/
  `tee`/`uniq` (each can write a file), `env` with a command, `mount` with arguments.

Like the approval policy, a seatbelt against a model's mistakes and not a boundary: the account
has sudo by design, and the program list is only as good as each program's flags.
"""
from app.tools.shellwords import simple_words


def _any(args: list[str]) -> bool:
    return True


def _no_args(args: list[str]) -> bool:
    return not args


def _first_word_in(*allowed: str, bare: bool = True):
    """The first non-option argument is one of `allowed` (or there is none, if `bare`)."""
    def check(args: list[str]) -> bool:
        words = [a for a in args if not a.startswith("-")]
        return (bare and not words) or (bool(words) and words[0] in allowed)
    return check


def _none_of(*forbidden: str):
    """No argument is, or starts with, a forbidden flag (`--vacuum` covers `--vacuum-size=1G`)."""
    def check(args: list[str]) -> bool:
        return not any(a == f or a.startswith(f + "=") or (f.startswith("--") and a.startswith(f))
                       for a in args for f in forbidden)
    return check


def _all_of(*checks):
    def check(args: list[str]) -> bool:
        return all(c(args) for c in checks)
    return check


def _only_options(*allowed: str, need_one: tuple[str, ...] = ()):
    """Every option is one of `allowed`; with `need_one`, at least one of those is present."""
    def check(args: list[str]) -> bool:
        options = [a for a in args if a.startswith("-")]
        if any(o not in allowed for o in options):
            return False
        return not need_one or any(o in need_one for o in options)
    return check


def _date(args: list[str]) -> bool:
    # `date -s …` and `date MMDDhhmm` set the clock; formats (`+%F`) and options only read it.
    return _none_of("-s", "--set")(args) and all(a.startswith(("+", "-")) for a in args)


def _ip(args: list[str]) -> bool:
    words = [a for a in args if not a.startswith("-")]
    if not words:
        return False
    objects = {"a", "addr", "address", "l", "link", "r", "route", "n", "neigh", "neighbour",
               "rule", "maddr", "maddress", "ntable"}
    actions = {"show", "list", "ls", "get"}
    return words[0] in objects and (len(words) == 1 or words[1] in actions)


def _sysctl(args: list[str]) -> bool:
    return _none_of("-w", "--write", "-p", "--load", "--system")(args) and not any("=" in a for a in args)


_DOCKER_READ = {"ps", "images", "inspect", "logs", "info", "version", "stats", "top", "port",
                "diff", "history"}
_DOCKER_GROUPS = {
    "compose": {"ps", "ls", "config", "logs", "images", "top", "version"},
    "container": {"ls", "list", "ps", "inspect", "logs", "top", "port", "diff", "stats"},
    "image": {"ls", "list", "inspect", "history"},
    "network": {"ls", "list", "inspect"},
    "volume": {"ls", "list", "inspect"},
    "system": {"df", "info"},
}


def _docker(args: list[str]) -> bool:
    words = [a for a in args if not a.startswith("-")]
    if not words:
        return False
    if words[0] in _DOCKER_GROUPS:
        return len(words) > 1 and words[1] in _DOCKER_GROUPS[words[0]]
    return words[0] in _DOCKER_READ


_GIT_READ = {"status", "log", "diff", "show", "rev-parse", "ls-files", "blame", "describe",
             "shortlog", "reflog"}


def _git(args: list[str]) -> bool:
    words = [a for a in args if not a.startswith("-")]
    if not words:
        return False
    if words[0] in _GIT_READ:
        return True
    rest = args[args.index(words[0]) + 1:]
    if words[0] == "branch":
        return _only_options("-a", "-r", "-v", "-vv", "--list", "--all")(rest) and all(a.startswith("-") for a in rest)
    if words[0] == "remote":
        return rest in ([], ["-v"], ["--verbose"])
    return False


COMMANDS = {
    **{name: _any for name in (
        "ls", "cat", "head", "tail", "stat", "file", "wc", "du", "df", "free", "uptime", "uname",
        "whoami", "id", "groups", "ps", "pgrep", "pidof", "lsblk", "blkid", "lscpu", "lspci",
        "lsusb", "lsmod", "findmnt", "ss", "which", "nproc", "echo", "pwd", "printenv", "getent",
        "w", "who", "last", "dig", "nslookup", "host", "ping", "sha256sum", "sha1sum", "md5sum",
        "readlink", "realpath", "basename", "dirname", "tree", "diff", "cmp", "lsof", "sensors",
        "getconf", "grep", "egrep", "fgrep", "zcat", "zgrep", "vmstat", "iostat", "mpstat",
        "lsattr", "getfacl", "namei", "dpkg-query", "arch", "tty", "uptime", "nl", "strings",
        "od", "hexdump", "xxd", "dmesg", "lsns", "lslocks", "lsipc", "numfmt",
    )},
    "hostname": _no_args,
    "env": _no_args,
    "mount": _no_args,
    "date": _date,
    "find": _none_of("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
                     "-fprintf", "-fls"),
    "systemctl": _first_word_in("status", "show", "list-units", "list-unit-files", "list-timers",
                                "list-sockets", "list-dependencies", "list-jobs", "is-active",
                                "is-enabled", "is-failed", "is-system-running", "cat", "get-default"),
    "journalctl": _none_of("--vacuum", "--rotate", "--flush", "--sync", "--relinquish-var",
                           "--smart-relinquish-var", "--setup-keys", "--update-catalog"),
    "ip": _ip,
    "docker": _docker,
    "apt": _first_word_in("list", "show", "policy", "search", "depends", "rdepends", "changelog", bare=False),
    "apt-cache": _first_word_in("show", "showpkg", "policy", "search", "depends", "rdepends",
                                "madison", "pkgnames", "stats", bare=False),
    "dpkg": _only_options("-l", "-L", "-s", "-S", "-p", "--list", "--listfiles", "--status",
                          "--search", "--print-avail", "--print-architecture", "--get-selections",
                          need_one=("-l", "-L", "-s", "-S", "-p", "--list", "--listfiles", "--status",
                                    "--search", "--print-avail", "--print-architecture",
                                    "--get-selections")),
    "git": _git,
    "ollama": _first_word_in("list", "ls", "ps", "show", "--version", "-v", bare=False),
    "nvidia-smi": lambda a: all(x in ("-q", "-L", "--list-gpus", "-a") or x.startswith(("--query", "--format"))
                                for x in a),
    "hostnamectl": _first_word_in("status", "show"),
    "timedatectl": _first_word_in("status", "show", "show-timesync", "timesync-status", "list-timezones"),
    "localectl": _first_word_in("status", "list-locales", "list-keymaps"),
    "networkctl": _first_word_in("list", "status", "lldp"),
    "resolvectl": _first_word_in("status", "query", "statistics"),
    "loginctl": _first_word_in("list-sessions", "list-users", "list-seats", "show-session",
                               "show-user", "session-status", "user-status"),
    "sysctl": _sysctl,
    "ufw": lambda a: bool(a) and a[0] == "status" and all(x in ("verbose", "numbered") for x in a[1:]),
    "nft": lambda a: bool(a) and [x for x in a if not x.startswith("-")][:1] == ["list"],
    "iptables": _only_options("-L", "-S", "-n", "-v", "-x", "-t", "--list", "--list-rules",
                              "--numeric", "--verbose", "--line-numbers", "--table",
                              need_one=("-L", "-S", "--list", "--list-rules")),
    "crontab": lambda a: a == ["-l"],
    "smartctl": _all_of(_none_of("-t", "--test", "-s", "--smart", "-o", "--offlineauto",
                                 "-S", "--saveauto", "-X", "--abort", "--set"),
                        lambda a: bool(a)),
}
COMMANDS["ip6tables"] = COMMANDS["iptables"]


def read_only(cmd) -> bool:
    """True when plan mode may run this `bash` command (see the module docstring)."""
    words = simple_words(cmd)
    if words is None:
        return False
    if words[0] == "sudo":
        words = words[1:]
        if words[:1] == ["-n"]:
            words = words[1:]
        if not words:
            return False
    name, args = words[0], words[1:]
    check = COMMANDS.get(name)
    if check is None:  # a path (`/usr/bin/rm`, `./ls`) is never a key, so it lands here too
        return False
    try:
        return bool(check(args))
    except Exception:
        return False  # a check that cannot decide must not allow
