from src.line_balancer.io_utils import read_operations
import pandas as pd
import tempfile
import os

print("=" * 60)
print("TESTING ID COLUMN VALIDATIONS")
print("=" * 60)

# Test 1: Null ID Cells
print('\n1. Test: Null ID Cells')
print('Expected: Should raise ValueError for missing/null ID')
try:
    df = pd.DataFrame({
        'Serial No.': [1, None, 3, 4, 5],  # Row 2 has null ID
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '3', '4'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for null ID')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 2: Duplicate IDs
print('\n2. Test: Duplicate IDs')
print('Expected: Should raise ValueError for duplicate IDs')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 2, 4, 5],  # ID 2 appears twice
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '3', '4'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for duplicate IDs')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 3: ID Not Starting from 1
print('\n3. Test: ID Not Starting from 1')
print('Expected: Should raise ValueError for IDs not starting from 1')
try:
    df = pd.DataFrame({
        'Serial No.': [2, 3, 4, 5, 6],  # IDs start from 2 instead of 1
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '2', '3', '4', '5'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for IDs not starting from 1')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 4: ID as 0 (not natural number)
print('\n4. Test: ID as 0 (not natural number)')
print('Expected: Should raise ValueError for ID = 0')
try:
    df = pd.DataFrame({
        'Serial No.': [0, 1, 2, 3, 4],  # ID 0 is not valid
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '0', '1', '2', '3'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for ID = 0')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 5: Negative ID
print('\n5. Test: Negative ID')
print('Expected: Should raise ValueError for negative ID')
try:
    df = pd.DataFrame({
        'Serial No.': [1, -2, 3, 4, 5],  # Negative ID
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '-2', '3', '4'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for negative ID')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 6: Multiple IDs in one cell
print('\n6. Test: Multiple IDs in one cell')
print('Expected: Should raise ValueError for multiple IDs in one cell')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 3, 4, 5],
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '3', '4'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    # Modify to have multiple IDs in one cell for Serial No.
    df.iloc[1, df.columns.get_loc('Serial No.')] = '2,3'  # Multiple IDs in one cell
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for multiple IDs in one cell')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test 7: Valid case - IDs from 1 to n
print('\n7. Test: Valid case - IDs from 1 to n')
print('Expected: Should pass validation')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 3, 4, 5],
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '3', '4'],
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        ops = read_operations(temp_file)
        print(f'PASSED: Validation succeeded, {len(ops)} operations loaded')
    except ValueError as e:
        print(f'FAILED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

print('\n' + '=' * 60)
print('ALL ID VALIDATION TESTS COMPLETED')
print('=' * 60)
