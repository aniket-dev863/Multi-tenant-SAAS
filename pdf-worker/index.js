const PDFDocument = require("pdfkit");
const { S3Client, PutObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// Initialize S3 Client (AWS automatically provides credentials inside Lambda)
const s3 = new S3Client({ region: "ap-south-1" });
const BUCKET_NAME = "streampulse-reports-aniket"; // Change this to your actual S3 bucket name

exports.handler = async (event) => {
  console.log("PDF Worker Triggered!");

  return new Promise((resolve, reject) => {
    try {
      // 1. Setup the PDF Document in Memory
      const doc = new PDFDocument({ margin: 50 });
      const buffers = [];

      doc.on("data", buffers.push.bind(buffers));

      // 2. Draw the PDF Design
      doc.fontSize(20).text(`${event.pharmacy_name}`, { align: "center" });
      doc.fontSize(14).text(`${event.report_type}`, { align: "center" });
      doc
        .fontSize(10)
        .text(`Date Range: ${event.date_range}`, { align: "center" });
      doc.moveDown(2);

      // Draw Table Headers
      doc.fontSize(12).font("Helvetica-Bold");
      doc.text("Date", 50, doc.y, { continued: true, width: 150 });
      doc.text("Customer", 200, doc.y, { continued: true, width: 200 });
      doc.text("Amount (INR)", 400, doc.y);
      doc
        .moveTo(50, doc.y + 5)
        .lineTo(550, doc.y + 5)
        .stroke();
      doc.moveDown();

      // Draw Rows from Flask Data
      doc.font("Helvetica").fontSize(10);
      let totalRevenue = 0;

      event.data.forEach((row) => {
        doc.text(row.date, 50, doc.y, { continued: true, width: 150 });
        doc.text(row.customer, 200, doc.y, { continued: true, width: 200 });
        doc.text(row.amount.toFixed(2), 400, doc.y);
        totalRevenue += row.amount;
        doc.moveDown(0.5);
      });

      doc.moveDown();
      doc
        .font("Helvetica-Bold")
        .text(`Total Revenue: ${totalRevenue.toFixed(2)} INR`, 400, doc.y);

      // Finalize PDF
      doc.end();

      // 3. When PDF is done building, upload to S3
      doc.on("end", async () => {
        const pdfBuffer = Buffer.concat(buffers);
        const fileName = `reports/${event.pharmacy_name.replace(/\s+/g, "_")}_${Date.now()}.pdf`;

        const command = new PutObjectCommand({
          Bucket: BUCKET_NAME,
          Key: fileName,
          Body: pdfBuffer,
          ContentType: "application/pdf",
        });

        await s3.send(command);

        // 4. Generate the temporary Presigned URL
        const getCommand = new PutObjectCommand({
          Bucket: BUCKET_NAME,
          Key: fileName,
        });
        const signedUrl = await getSignedUrl(s3, getCommand, {
          expiresIn: 300,
        }); // 5 minute expiry

        resolve({
          statusCode: 200,
          body: JSON.stringify({ download_url: signedUrl }),
        });
      });
    } catch (error) {
      console.error(error);
      resolve({
        statusCode: 500,
        body: JSON.stringify({ error: "Failed to generate PDF" }),
      });
    }
  });
};
