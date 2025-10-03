# Test Suite Structure

- **unit_tests**  
    These tests are intended to be run during development and are executed by default when you run `pytest`. They are fast, isolated, and do not require any external dependencies.

- **system_tests**  
    These tests connect to external processes or services. They are primarily intended to be run in Continuous Integration (CI) environments and may require additional setup or dependencies.
