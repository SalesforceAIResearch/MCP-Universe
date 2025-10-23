Perform a comprehensive products and sales analysis in the Magento Admin panel to identify inventory status and sales performance metrics.

**Task Requirements:**

1. if need to login, login with username 'admin' and password 'admin1234'

2. Analyze product inventory and catalog details, perform the following:
   - Search for all products containing 'Yoga' in their name - count the exact number of results
   - Clear the search and find the product with SKU 'WH11' - record its exact price
   - Apply a filter to show only products with Quantity = 0.0000 - count how many products match

3. To identify top-selling products and revenue metrics, navigate to the Dashboard and from the Bestsellers table:
   - Identify the product with lowest price and lowest quantity - record the product name and quantity sold
   - Find the second cheapest product in the table - record its exact quantity sold
   - Note the total Revenue amount displayed in the dashboard

4. Father all customers' information and demographics:
   - Find customer 'Sarah Miller' - record her exact email address
   - Count the total number of customers shown in the grid

5. Review order status and customer purchase history, go to orders of sales:
   - Count the total number of orders with 'Pending' status
   - Find the order ID of Grace Nguyen's order with the completed status and the most expensive price (starting with "000")

6. To provide a comprehensive report of all gathered data, compile all your findings and output them in the following exact format:

```
<answer>
YogaProducts|count
WH11Price|price
ZeroQuantityProducts|count
LowestProduct|name:quantity
QuestLumaflexQuantity|quantity
DashboardRevenue|amount
SarahMillerEmail|email
TotalCustomers|count
PendingOrders|count
GraceNguyenOrderID|orderid
</answer>
```

**Example Output:**
```
<answer>
YogaProducts|XX
WH11Price|$XX.XX
ZeroQuantityProducts|XX
LowestProduct|Product Name Here:XX
QuestLumaflexQuantity|XX
DashboardRevenue|$XX.XX
SarahMillerEmail|email@example.com
TotalCustomers|XX
PendingOrders|X
GraceNguyenOrderID|00000XXXX
</answer>
```