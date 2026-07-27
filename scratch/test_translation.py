import sys
sys.path.insert(0, '.')
from database import translate_sqlite_to_mysql

# Test 1: get_daily_attendance query - was failing
q1 = """SELECT a.entry_time, a.exit_time, s.name, s.role,
    (CASE WHEN a.exit_time IS NOT NULL 
          THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime')) 
          ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) / 3600.0,
    s.salary_type, a.is_late, a.active_seconds
FROM attendance a JOIN staff s ON a.staff_id = s.id
WHERE date(a.entry_time, 'localtime') = date(?, 'localtime')
ORDER BY a.entry_time DESC"""
print('=== Test 1: get_daily_attendance ===')
result1 = translate_sqlite_to_mysql(q1)
print(result1)
assert "date(%s, 'localtime')" not in result1, "FAIL: parameterized date() not translated!"
assert "DATE(%s)" in result1, "FAIL: DATE(%s) not found!"
print('PASS\n')

# Test 2: system_settings key query - was failing
q2 = "SELECT value FROM system_settings WHERE key = 'late_grace_minutes'"
print('=== Test 2: system_settings key ===')
result2 = translate_sqlite_to_mysql(q2)
print(result2)
assert "`key`" in result2, "FAIL: key not escaped!"
assert "`value`" in result2, "FAIL: value not escaped!"
print('PASS\n')

# Test 3: wellness_threshold
q3 = "SELECT value FROM system_settings WHERE key = 'wellness_threshold'"
print('=== Test 3: wellness_threshold ===')
result3 = translate_sqlite_to_mysql(q3)
print(result3)
assert "`key`" in result3, "FAIL: key not escaped!"
print('PASS\n')

print('All tests passed!')
