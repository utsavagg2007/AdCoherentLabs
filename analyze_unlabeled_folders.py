import os
from collections import Counter

unlabeled_dir = "data/unlabeled"
folders = [f for f in os.listdir(unlabeled_dir) if os.path.isdir(os.path.join(unlabeled_dir, f))]

for folder in sorted(folders):
    path = os.path.join(unlabeled_dir, folder)
    exts = [os.path.splitext(f)[1] for f in os.listdir(path)]
    c = Counter(exts)
    print(f"Folder {folder}: {dict(c)}")
