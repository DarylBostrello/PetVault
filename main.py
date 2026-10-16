#!/usr/bin/env python3
"""Start PetVault.

    python main.py            # open the app
    python main.py --demo     # load sample data and demo logins first
    python main.py --db FILE  # use a different database file
"""
from petvault.ui.app import main

if __name__ == "__main__":
    main()
