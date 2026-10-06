# What students ask at the counter

Short, true answers. For the founder and the shopkeeper to say out loud.

**1. Do I need an app or an account?**
No. Scan the sign, it opens in your browser. It does not ask for your name, number or email.

**2. What files can I send?**
One PDF at a time, up to 25 MB, printed on A4. Word files and photos: save them as a PDF first. A PDF with a password is refused; remove the password.

**3. How much is it, and how do I pay?**
You see the exact price before you press "Send to shop". You pay here at the counter when you collect. Nothing is paid online.

**4. Can I choose copies, colour, both sides, only some pages?**
Yes: black and white or colour, one side or both sides, 1 to 100 copies, all pages or a range like 1-3, 5. The price changes as you choose. For a second file, send a second order.

**5. How do I know it is ready?**
Keep the page open; it updates by itself. When it says "Sent to printer. Collect it at the counter." tell the shopkeeper the 4-character order code on your screen.

**6. Who can see my file?**
The shopkeeper, who can look at it before printing, the same as when you send it on WhatsApp. Nobody else: it is not public, and the shop computer does not keep a copy after printing.

**7. What happens to my file afterwards?**
It is deleted by itself 24 hours after your order ends (printed, declined or cancelled), and never later than 48 hours after you started. A file you uploaded but never sent is deleted after 1 hour. The order record stays (code, file name, page count, price, times), without the file. Want it gone sooner? Give the shopkeeper your order code and it is deleted on request.

**8. Can I cancel or change it?**
Before you send: press "Change settings" or "Choose another file". After you send: "Cancel this print" works until printing starts, then send it again the way you want. Once printing has started it cannot be cancelled.

**9. It just says "Waiting for the shop to approve". Is it stuck?**
No, the shopkeeper has not pressed approve yet. Tell them your code. They have 1 hour; after that the order closes and you send it again. You can send from home too, but only within that hour. If you closed the page, open the site again in the same browser and tap "Your order".

**10. It says "declined", "could not print" or "the shop is checking this print". What now?**
Ask at the counter with your code. Declined means the shopkeeper refused it and will tell you why. The other two mean the printer had a problem and the shopkeeper is sorting it out. You pay only for pages you are handed.

---

Notes for the founder, not for students:

- Answer 7 is what the retention rules in the database do (1 hour, 24 hours, 48 hours). It has been proven by tests, not yet by waiting out a real 24-hour window on the live system.
- Deleting on request is `scripts/ap_remote.py purge CODE XXXX`. It is refused while the job is still waiting, approved or printing; reject or cancel it first.
- The file name stays in the order record after the file is deleted. Say so if someone asks; do not promise "everything is deleted".
- "Sent to printer" means the print left the Windows queue. Never tell a student "the app says it printed".
