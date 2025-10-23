Please help me create a comprehensive security audit ticket based on the data already stored in the **IT Trouble Shooting Hub** page.

Your automation should:

1. In the **IT Inventory** database, find every item whose **Expiration date** is **before 2023-07-15**.
2. In the **IT FAQs** database, look up any FAQ entries that have the **"Security"** tag.
3. **Create a new page** inside the **IT Requests** database with **exact title**:
   
   `Quarterly Security Audit - Expired Assets Review`
4. Set its **Priority** property to **High**.
5. Set its **Due** property to **2023-06-22**.
6. In the page body, add a bullet-list block that enumerates **each expired inventory item**. **Each bullet item must follow this exact text format (including the dashes):**

   `<Serial> - <Tag> - <Recommendation>`

   • `<Serial>` is the item’s Serial value.
   • `<Tag>` is the first tag assigned to the inventory item (e.g., "Laptop").
   • `<Recommendation>` is a brief action you suggest based on the security FAQ entry (any text is acceptable).

   Example (do **not** copy):
   `ABC123 - Laptop - Renew warranty and enable disk encryption`