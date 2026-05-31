-- Create schemas matching dbt's medallion architecture
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;

-- Grant usage to the admin user
GRANT ALL ON SCHEMA raw TO my_aba_admin;
GRANT ALL ON SCHEMA staging TO my_aba_admin;
GRANT ALL ON SCHEMA marts TO my_aba_admin;