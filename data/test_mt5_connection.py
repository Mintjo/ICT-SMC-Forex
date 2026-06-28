"""Quick standalone MT5 connection test.

Loads credentials from environment variables (or a .env file via
python-dotenv if present), connects to the MT5 terminal, prints account
and terminal info, then disconnects. Exits with a non-zero status code
on failure so it can gate a setup script.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from data.mt5_connector import MT5Connector, mt5


def main():
    connector = MT5Connector()
    if not connector.connect(retries=3):
        print("ECHEC : impossible de se connecter au terminal MT5.")
        sys.exit(1)

    account = mt5.account_info()
    terminal = mt5.terminal_info()
    print("Connexion MT5 reussie.")
    if account:
        print(f"Compte       : {account.login} ({account.server})")
        print(f"Solde        : {account.balance} {account.currency}")
    if terminal:
        print(f"Terminal     : {terminal.name} build {terminal.build}")

    connector.shutdown()


if __name__ == "__main__":
    main()
