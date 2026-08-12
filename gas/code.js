/**
 * Google Apps Script (GAS) Web App Email Receiver
 * 
 * Instructions:
 * 1. Open script.google.com and create a new project.
 * 2. Paste this code into the editor.
 * 3. Replace "YOUR_SHARED_SECRET_TOKEN" with a secure random token.
 * 4. Replace "your-email@example.com" with your destination email address.
 * 5. Click "Deploy" -> "New deployment".
 * 6. Select type "Web app".
 * 7. Set "Execute as" to "Me" and "Who has access" to "Anyone".
 * 8. Deploy, authorize permissions, and copy the Web App URL.
 * 9. Set the URL and Secret Token in your GitHub Secrets as:
 *    - GAS_WEBAPP_URL: <Copied Web App URL>
 *    - GAS_SECRET_TOKEN: <Your Secret Token>
 */

var SHARED_SECRET_TOKEN = "YOUR_SHARED_SECRET_TOKEN"; // CHANGE THIS to a secure token
var DESTINATION_EMAIL = "your-email@example.com";     // CHANGE THIS to your email

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    
    // Authorization Check
    if (!data.secret || data.secret !== SHARED_SECRET_TOKEN) {
      return ContentService.createTextOutput(JSON.stringify({
        "status": "error",
        "message": "Unauthorized: Invalid secret token"
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // Required fields check
    if (!data.subject || !data.html_body) {
      return ContentService.createTextOutput(JSON.stringify({
        "status": "error",
        "message": "Bad Request: Missing subject or html_body"
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // Send email using GmailApp service
    GmailApp.sendEmail(DESTINATION_EMAIL, data.subject, "", {
      htmlBody: data.html_body,
      name: "BMW Specsheet Monitor"
    });
    
    return ContentService.createTextOutput(JSON.stringify({
      "status": "success",
      "message": "Email sent successfully"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      "status": "error",
      "message": "Server Error: " + err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
