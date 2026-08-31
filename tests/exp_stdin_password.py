"""Чи ЧИТАЄ цей svn пароль зі stdin, а не просто приймає прапорець.

SlikSvn 1.14.2 --password-from-stdin приймала мовчки й ігнорувала, через що
кожна мережева дія падала з Authentication failed. Перевірка «є в help» цього
не ловить, а file://-репозиторій не ловить поготів: там автентифікації немає.
Тому піднімаємо справжній svnserve, який ВИМАГАЄ пароль.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
import desktop
import svn_client as sc

# Беремо той самий svn, яким користується сам APSVN, а не будь-який із PATH:
# питання ж саме про НЬОГО.
SVN = sc.SVN or shutil.which("svn")
SVNADMIN = shutil.which("svnadmin")
SVNSERVE = shutil.which("svnserve")
print("svn:", SVN)
print("supports_stdin_password() каже:", sc.supports_stdin_password())
print("версія:", subprocess.run([SVN, "--version", "--quiet"],
                                capture_output=True, text=True).stdout.strip())

base = tempfile.mkdtemp(prefix="apsvn_stdinpw_")
repo = os.path.join(base, "repo")
subprocess.run([SVNADMIN, "create", repo], check=True)
with open(os.path.join(repo, "conf", "svnserve.conf"), "w") as fh:
    fh.write("[general]\nanon-access = none\nauth-access = write\n"
             "password-db = passwd\nrealm = apsvn-test\n")
with open(os.path.join(repo, "conf", "passwd"), "w") as fh:
    fh.write("[users]\nbob = s3cret\n")

with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
srv = subprocess.Popen([SVNSERVE, "-d", "--foreground", "--listen-host",
                        "127.0.0.1", "--listen-port", str(port), "-r", base])
time.sleep(1.5)
url = "svn://127.0.0.1:%d/repo" % port
cfg = os.path.join(base, "cfg")

def run(args, stdin_data=None):
    return subprocess.run([SVN] + args + ["--non-interactive", "--no-auth-cache",
                                          "--config-dir", cfg],
                          input=stdin_data, capture_output=True, timeout=60)

try:
    # Осердя пастки: без -v Homebrew-збірка глобальних опцій не показує
    # взагалі, тож наївна проба каже «не вміє» про той svn, який вміє.
    plain = "--password-from-stdin" in run(["help", "status"]).stdout.decode()
    verb = "--password-from-stdin" in run(["help", "status", "-v"]).stdout.decode()
    print("\n1. 'svn help status'    містить прапорець:", plain)
    print("   'svn help status -v' містить прапорець:", verb)

    r = run(["ls", url, "--username", "bob", "--password-from-stdin"],
            b"s3cret\n")
    print("2. ПРАВИЛЬНИЙ пароль через stdin -> rc=%d %s" %
          (r.returncode, "OK" if r.returncode == 0 else
           r.stderr.decode(errors="replace").strip()[:120]))
    good = r.returncode == 0

    r = run(["ls", url, "--username", "bob", "--password-from-stdin"],
            b"WRONG-PASSWORD\n")
    print("3. НЕПРАВИЛЬНИЙ пароль через stdin -> rc=%d %s" %
          (r.returncode, "OK(!)" if r.returncode == 0 else
           r.stderr.decode(errors="replace").strip()[:80]))
    rejects = r.returncode != 0

    r = run(["ls", url, "--username", "bob", "--password", "s3cret"])
    print("4. пароль через --password (запасний шлях) -> rc=%d" % r.returncode)

    print()
    if good and rejects:
        print("ВИСНОВОК: stdin справді ЧИТАЄТЬСЯ — правильний пароль пускає,")
        print("          неправильний ні. Запасний шлях через argv не потрібен.")
    elif good and not rejects:
        print("ВИСНОВОК: пускає будь-що — прапорець ІГНОРУЄТЬСЯ (як SlikSvn).")
    else:
        print("ВИСНОВОК: stdin НЕ працює — потрібен запасний шлях через argv.")
finally:
    srv.terminate(); srv.wait()
    shutil.rmtree(base, ignore_errors=True)
