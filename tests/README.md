# Testing
check https://inkscape.gitlab.io/extensions/documentation/authors/unit-tests.html

1. produce a .svg file: 
    EXPORT_COMPARE=1 pytest tests/test_laserjoints.py

2. test if the result is ok with inkscape

3. rename to ".out", this will make it eligible for comparison

4. perform test 
    EXPORT_COMPARE=2 pytest tests/test_laserjoints.py

5. there should be no error.
