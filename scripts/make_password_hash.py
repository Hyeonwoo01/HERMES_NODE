"""Print a PBKDF2 hash to paste into the deployment's secrets (never commit passwords).

    python scripts/make_password_hash.py

Then add to .streamlit/secrets.toml (local) or the app's Secrets (Streamlit Cloud):

    [auth.users.nurse_kim]
    name = "전원 간호사 김OO"
    role = "coordinator"          # viewer | coordinator | supervisor
    password_hash = "pbkdf2_sha256$600000$..."
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synapse_h.auth import hash_password  # noqa: E402

if __name__ == "__main__":
    pw = getpass.getpass("비밀번호: ")
    if len(pw) < 12:
        sys.exit("12자 이상으로 정하세요.")
    if pw != getpass.getpass("다시 입력: "):
        sys.exit("두 입력이 다릅니다.")
    print(hash_password(pw))
