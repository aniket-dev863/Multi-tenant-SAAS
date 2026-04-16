const { Client } = require('pg');

exports.handler = async (event) => {
    console.log("Waking up Lambda to check for expired batches...");

    const client = new Client({
        host: process.env.RDS_HOST,
        database: process.env.RDS_DB,
        user: process.env.RDS_USER,
        password: process.env.RDS_PASSWORD,
        port: 5432,
        ssl: { rejectUnauthorized: false } 
    });

    try {
        await client.connect();

        const updateQuery = `
            UPDATE batches
            SET status = 'Expired'
            WHERE expiry_date < CURRENT_DATE 
            AND status = 'Active';
        `;

        const res = await client.query(updateQuery);
        const updatedCount = res.rowCount;

        console.log(`Success! Marked ${updatedCount} batches as Expired.`);

        return {
            statusCode: 200,
            body: `Successfully updated ${updatedCount} expired batches.`
        };

    } catch (err) {
        console.error("Database Error:", err);
        return {
            statusCode: 500,
            body: err.message
        };
    } finally {
        await client.end();
    }
};
