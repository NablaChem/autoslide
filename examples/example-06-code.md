### Getting Started

```python
# pip install --upgrade nablachem
import nablachem.space as ncs
counter = ncs.ApproximateCounter(show_progress=False)
space = ncs.SearchSpace("H:1 O:2 C:4 N:3")
criterion = ncs.Q("C = 8 & H = 10 & N = 4 & O = 2")
natoms = 24

total_molecule_count = counter.count(space, natoms, criterion)
mols = ncs.random_sample(
    counter, space, natoms=natoms, nmols=3, selection=criterion
)
```

[*] Sample code, needs work for research.
