# PetVault

**Veterinary Clinic Patient & Appointment Management System**: a Tkinter desktop app with an SQLite database. Standard library only (Python 3.9+; on Linux you may need Tk: `sudo pacman -S tk` or `sudo apt install python3-tk`).

## Run it

```
python main.py            # open the app
python main.py --demo     # load sample data and demo logins first
python main.py --db FILE  # use a different database file
```

(`python -m petvault` works too.) The database `petvault.db` is created next to `main.py`.
**Moving from the old single file?** Copy your existing `petvault.db` next to `main.py` and your data comes with you.

The first run asks you to create the administrator account. With `--demo` the logins are
`admin / admin123`, `reception / reception123` and `dr.cruz / vet12345`.

## Where things live

```
main.py                 start the app
petvault/               the program
    (data and rules, no Tk)
    config, errors, utils, security, schema, database, files, demo
    ui/                 the Tkinter interface
        widgets/        one file per reusable widget
        dialogs/        one file per pop-up dialog
        pages/          one file per screen
tests/test_database.py  database and rules tests (needs no Tk)
```

| File | What it does |
|---|---|
| `petvault/config.py` | Settings and fixed values: file locations, date formats, roles, permissions, payment methods. |
| `petvault/database.py` | The Clinic class: every database operation and business rule (no screens in here). |
| `petvault/demo.py` | Sample data and demo logins for the --demo option. |
| `petvault/errors.py` | The one error type used for every validation or business-rule problem. |
| `petvault/files.py` | CSV export, a tiny PDF writer, receipt and summary text, and opening files. |
| `petvault/schema.py` | The SQLite table definitions and the small migrations for older database files. |
| `petvault/security.py` | Password hashing (PBKDF2) and checking. |
| `petvault/utils.py` | Small pure helpers: parsing dates, times and money, formatting, slot times. |
| `petvault/ui/app.py` | VetApp: the main window, sidebar and navigation, plus the program's main() entry point. |
| `petvault/ui/constants.py` | Fixed lists used by the screens: species, appointment times, schedule times. |
| `petvault/ui/drawing.py` | Drawing helpers: rounded rectangles and the paw print. |
| `petvault/ui/helpers.py` | Small helpers shared by the screens: card titles, labelled fields, selection and prompts. |
| `petvault/ui/icon.py` | The window icon (a paw print embedded as PNG data). |
| `petvault/ui/login.py` | LoginView: the sign-in screen (and first-run administrator setup). |
| `petvault/ui/page_registry.py` | The list of screens (in menu order). |
| `petvault/ui/pager.py` | The Pager class: shows 10 table rows at a time with Previous / Next. |
| `petvault/ui/table_rows.py` | Low-level table helpers: filling rows, sizing columns, auto-hiding scrollbars. |
| `petvault/ui/tables.py` | Builds tables (with scrollbars and the pager) and fills them with rows. |
| `petvault/ui/theme.py` | Colours, the shared font name and the ttk theme for tables and scrollbars. |
| `petvault/ui/dialogs/form_dialog.py` | FormDialog: a small rounded pop-up form used for edits, payments, voiding and more. |
| `petvault/ui/dialogs/modal.py` | Helpers to place a dialog over the main window and block the window behind it. |
| `petvault/ui/dialogs/profile_dialog.py` | ProfileDialog: everything about one patient on a single screen. |
| `petvault/ui/dialogs/schedule_dialog.py` | ScheduleDialog: edit a veterinarian's weekly hours and days off. |
| `petvault/ui/pages/admin.py` | The Admin screen: staff accounts and backups. |
| `petvault/ui/pages/appointments.py` | The Appointments screen. |
| `petvault/ui/pages/base.py` | BasePage: what every screen has in common. |
| `petvault/ui/pages/billing.py` | The Billing screen. |
| `petvault/ui/pages/dashboard.py` | The Dashboard screen. |
| `petvault/ui/pages/patients.py` | The Patients screen. |
| `petvault/ui/pages/records.py` | The Medical Records screen. |
| `petvault/ui/pages/reports.py` | The Reports screen. |
| `petvault/ui/pages/vets.py` | The Veterinarians screen. |
| `petvault/ui/widgets/bar_chart.py` | BarChart: the simple bar chart on the dashboard. |
| `petvault/ui/widgets/calendar_popup.py` | CalendarPopup: a month calendar that opens under a date field. |
| `petvault/ui/widgets/card.py` | Card: a rounded panel. |
| `petvault/ui/widgets/nav_button.py` | NavButton: a sidebar menu item shaped like a pill. |
| `petvault/ui/widgets/pill_button.py` | PillButton: a rounded button with hover and press feedback. |
| `petvault/ui/widgets/rounded_field.py` | RoundedField: a rounded text box that can also be a searchable dropdown or a date picker. |
| `petvault/ui/widgets/stat_card.py` | StatCard: a pastel summary tile. |
| `petvault/ui/widgets/toggle_button.py` | ToggleButton: a small on/off pill (for example Working / Day off). |

## When something goes wrong, open this file

| Problem | Look in |
|---|---|
| A rule is wrong (booking, vet hours, voiding, deleting, login) | `petvault/database.py` |
| A table or column is missing or needs a new field | `petvault/schema.py` |
| A screen looks or behaves wrongly | `petvault/ui/pages/<screen>.py` |
| A pop-up (edit, reschedule, complete visit, payment, void) | `petvault/ui/dialogs/` |
| A button, text box, dropdown or calendar misbehaves | `petvault/ui/widgets/` |
| A table, paging or column widths | `petvault/ui/tables.py`, `pager.py`, `table_rows.py` |
| Colours or fonts | `petvault/ui/theme.py` |
| Who may do what | `PERMISSIONS` in `petvault/config.py` |
| Receipts, PDF and CSV | `petvault/files.py` |
| Sample data | `petvault/demo.py` |

## Check the rules still work

```
python tests/test_database.py
```
