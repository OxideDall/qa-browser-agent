"""MetaMask onboarding automation — drives the agent through seed phrase import."""

import sys
from pathlib import Path

from .agent import run_task
from .config import METAMASK_EXT, PROFILE_DIR, TEST_PASSWORD, TEST_SEED


def setup_metamask(headless: bool = False, verbose: bool = True,
                   seed: str | None = None,
                   password: str | None = None,
                   profile_dir: Path | None = None) -> str:
    """Auto-setup MetaMask with a seed phrase using the QA agent.

    Defaults to TEST_SEED + TEST_PASSWORD + PROFILE_DIR from config — callers
    (e.g. the bench harness) pass their own seed/profile to isolate wallets.
    """
    if not METAMASK_EXT.exists():
        print(f"MetaMask not found at {METAMASK_EXT}", file=sys.stderr)
        print(
            "Download: wget https://github.com/MetaMask/metamask-extension/"
            "releases/download/v13.24.0/metamask-chrome-13.24.0.zip"
        )
        sys.exit(1)

    seed = seed or TEST_SEED
    password = password or TEST_PASSWORD
    prof = profile_dir if profile_dir is not None else PROFILE_DIR

    task = (
        f"MetaMask onboarding is open. Complete the wallet setup:\n"
        f"1. Click 'Import an existing wallet' (NOT create new)\n"
        f"2. Click 'I agree' or 'No thanks' on metrics\n"
        f"3. Enter this EXACT seed phrase: {seed}\n"
        f"   Type all words separated by spaces into the text area/field.\n"
        f"   IMPORTANT: After typing, click somewhere else on the page to trigger validation.\n"
        f"   If button stays disabled, try clicking outside the text area first, then click the button.\n"
        f"4. Click 'Confirm Secret Recovery Phrase' or 'Continue'\n"
        f"5. Set password to: {password} (type in both password fields)\n"
        f"6. Check the terms checkbox if present\n"
        f"7. Click 'Import my wallet' or 'Create password'\n"
        f"8. Click through any 'Got it' / 'Next' / 'Done' screens\n"
        f"9. When you see the MetaMask main dashboard with account balance, done PASS"
    )

    print("Setting up MetaMask with the provided wallet...")
    print(f"  Seed length: {len(seed.split())} words")
    print(f"  Profile: {prof}")

    status, desc, _ = run_task(
        task=task,
        url=None,
        headless=headless,
        verbose=verbose,
        max_steps=40,
        extensions=[str(METAMASK_EXT)],
        profile_dir=prof,
    )

    if status == "PASS":
        print("\nMetaMask setup complete! Profile saved for future runs.")
    else:
        print(f"\nMetaMask setup failed: {desc}")
        print("Try running without --headless to watch and debug.")
    return status
