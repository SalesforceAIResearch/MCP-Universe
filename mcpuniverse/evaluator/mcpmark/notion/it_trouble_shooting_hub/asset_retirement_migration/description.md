Please restructure the **IT Inventory** database as described below. Your automation will be checked by an automated script, so follow every detail exactly.

---
Task Steps
1. Inside the **IT Trouble Shooting Hub** page, locate the database named **IT Inventory**.
2. Query this database and collect every page whose **Status** property is **Expired** or **To be returned**.
3. Create a **new full-page database** directly under the same IT Trouble Shooting Hub page called **IT Asset Retirement Queue**.
4. Configure this new database so that it contains **exactly** the following properties (spellings and types must match):
   • Serial – title  
   • Tags – multi_select  
   • Status – select  
   • Vendor – select  
   • Expiration date – date  
   • Retirement Reason – select with option set { **Expired License**, **Hardware Obsolete**, **Security Risk**, **User Offboarding** }
5. For every inventory item gathered in step2:
   a. Create a corresponding page in **IT Asset Retirement Queue** and copy over the values of the Serial, Tags, Status, Vendor and Expiration date properties.  
   b. Set **Retirement Reason** to one of the four options above (choose the most appropriate).  
   c. Archive the original inventory page **after** the new page has been created.
6. After all items are migrated:
   a. Update the **description** of the **IT Asset Retirement Queue** database so it is **exactly** `AUTO-GENERATED MIGRATION COMPLETED` (no additional text).
   b. Create a new page under **IT Trouble Shooting Hub** titled **Retirement Migration Log**. Inside this page, add a **callout block** whose text follows the exact pattern:

      `Successfully migrated <N> assets to the retirement queue on 2025-03-24.`

      • `<N>` is the total number of items moved.