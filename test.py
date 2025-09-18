import smtplib
server = smtplib.SMTP("smtp.gmail.com", 587)
server.ehlo()
server.starttls()
server.login("sunilramtri000@gmail.com", "dbym tlab ejkq mrex")
print("✅ Login successful")
server.quit()
