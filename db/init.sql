CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    city        TEXT,
    country     TEXT,
    signup_date DATE NOT NULL
);
CREATE TABLE products (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL,
    price    NUMERIC(10,2) NOT NULL
);
CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers(id),
    order_date   DATE NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('completed','cancelled','returned')),
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0
);
CREATE TABLE order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL REFERENCES orders(id),
    product_id INT NOT NULL REFERENCES products(id),
    quantity   INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);

COMMENT ON COLUMN orders.total_amount IS 'Order value in USD (sum of quantity * unit_price of its items)';
COMMENT ON COLUMN orders.status IS 'Lifecycle state of the order';
COMMENT ON COLUMN customers.signup_date IS 'Date the customer registered';

-- Deterministic seed data (no randomness, so eval gold answers are reproducible)
INSERT INTO customers (name, email, city, country, signup_date)
SELECT 'Customer ' || i, 'customer' || i || '@example.com',
       (ARRAY['Kolkata','Mumbai','New York','Austin','London','Leeds'])[1 + (i % 6)],
       (ARRAY['India','India','USA','USA','UK','UK'])[1 + (i % 6)],
       DATE '2023-01-01' + (i * 7)
FROM generate_series(1, 50) i;

INSERT INTO products (name, category, price)
SELECT 'Product ' || i, (ARRAY['Electronics','Books','Home','Toys'])[1 + (i % 4)], 10 + ((i * 13) % 90)
FROM generate_series(1, 20) i;

INSERT INTO orders (customer_id, order_date, status, total_amount)
SELECT 1 + ((i * i) % 50), DATE '2024-01-01' + (i * 2),
       CASE WHEN i % 10 = 0 THEN 'cancelled' WHEN i % 7 = 0 THEN 'returned' ELSE 'completed' END, 0
FROM generate_series(1, 300) i ORDER BY i;

INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.id, 1 + ((o.id * k * 5) % 20), 1 + ((o.id + k) % 4), p.price
FROM orders o
CROSS JOIN generate_series(1, 3) k
JOIN products p ON p.id = 1 + ((o.id * k * 5) % 20)
WHERE k <= 1 + (o.id % 3);

UPDATE orders o SET total_amount = s.t
FROM (SELECT order_id, SUM(quantity * unit_price) AS t FROM order_items GROUP BY order_id) s
WHERE s.order_id = o.id;
