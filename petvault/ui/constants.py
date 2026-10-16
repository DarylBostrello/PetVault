"""Fixed lists used by the screens: species, appointment times, schedule times."""

from petvault.config import DEFAULT_END, DEFAULT_START
from petvault.utils import from_minutes, slot_times


SPECIES = ["Dog", "Cat", "Rabbit", "Bird", "Hamster", "Reptile", "Other"]
TIME_SLOTS = slot_times(DEFAULT_START, DEFAULT_END)
SCHEDULE_TIMES = [from_minutes(m) for m in range(5 * 60, 22 * 60 + 1, 30)]
