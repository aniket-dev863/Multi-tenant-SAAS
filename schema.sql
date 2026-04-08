-- 0. PHARMACIES (NEW: The Core SaaS Tenant Table)
CREATE TABLE pharmacies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 1. USERS (Modified: Added pharmacy_id)
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'pharmacist')),
    pharmacy_id INT REFERENCES pharmacies(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. SUPPLIERS (Modified: Added pharmacy_id)
CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    address TEXT,
    pharmacy_id INT REFERENCES pharmacies(id) ON DELETE CASCADE
);

-- 3. MEDICINES (Modified: Added pharmacy_id)
CREATE TABLE medicines (
    medicine_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    generic_name VARCHAR(150),
    brand_name VARCHAR(100),
    category VARCHAR(50) CHECK (category IN ('Tablet', 'Syrup', 'Injection', 'Cream', 'Other')),
    manufacturer VARCHAR(100),
    supplier_id INT REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
    pharmacy_id INT REFERENCES pharmacies(id) ON DELETE CASCADE
);

-- 4. BATCHES (Unchanged: Isolated automatically via medicine_id)
CREATE TABLE batches (
    batch_id SERIAL PRIMARY KEY,
    medicine_id INT REFERENCES medicines(medicine_id) ON DELETE CASCADE,
    batch_code VARCHAR(50) NOT NULL,
    expiry_date DATE NOT NULL,
    quantity INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    buy_price DECIMAL(10, 2) NOT NULL,
    sell_price DECIMAL(10, 2) NOT NULL,
    entry_date DATE DEFAULT CURRENT_DATE,
    UNIQUE(medicine_id, batch_code)
);

-- 5. SALES (Modified: Added pharmacy_id)
CREATE TABLE sales (
    sale_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    pharmacy_id INT REFERENCES pharmacies(id) ON DELETE CASCADE,
    sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    customer_name VARCHAR(100),
    total_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00
);

-- 6. SALE ITEMS (Unchanged: Isolated automatically via sale_id)
CREATE TABLE sale_items (
    sale_item_id SERIAL PRIMARY KEY,
    sale_id INT REFERENCES sales(sale_id) ON DELETE CASCADE,
    batch_id INT REFERENCES batches(batch_id),
    quantity INT NOT NULL CHECK (quantity > 0),
    price_per_unit DECIMAL(10, 2) NOT NULL,
    total_price DECIMAL(10, 2) GENERATED ALWAYS AS (quantity * price_per_unit) STORED
);

-- TRIGGER FUNCTION (Unchanged)
CREATE OR REPLACE FUNCTION update_stock_after_sale()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE batches
    SET quantity = quantity - NEW.quantity
    WHERE batch_id = NEW.batch_id;

    IF (SELECT quantity FROM batches WHERE batch_id = NEW.batch_id) < 0 THEN
        RAISE EXCEPTION 'Insufficient stock for this batch.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- TRIGGER (Unchanged)
CREATE TRIGGER trg_reduce_stock
AFTER INSERT ON sale_items
FOR EACH ROW
EXECUTE FUNCTION update_stock_after_sale();

-- SEED DATA (Modified to support the new constraints)
INSERT INTO pharmacies (name) VALUES ('City Hospital Pharmacy'), ('Apollo Care Pharmacy');

-- Note: The dummy password 'admin123' below is NOT hashed. 
-- You will not be able to log in with this dummy user using the new login route.
-- It is recommended to register a new user via the UI to generate a valid Werkzeug hash.
-- Seed admin user removed. Use the /register route to create users with properly hashed passwords.
-- To create an admin manually, run this in psql after generating a hash via Python:
-- python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"
-- Then: INSERT INTO users (username, password_hash, role, pharmacy_id) VALUES ('admin_city', '<paste_hash_here>', 'admin', 1);

INSERT INTO suppliers (name, phone, pharmacy_id) VALUES ('HealthCorp', '9876543210', 1);
INSERT INTO medicines (name, generic_name, category, manufacturer, supplier_id, pharmacy_id) VALUES ('Dolo 650', 'Paracetamol 650mg', 'Tablet', 'Micro Labs', 1, 1);
INSERT INTO batches (medicine_id, batch_code, expiry_date, quantity, buy_price, sell_price) VALUES (1, 'BATCH-X99', CURRENT_DATE + INTERVAL '1 year', 100, 25.00, 30.00);