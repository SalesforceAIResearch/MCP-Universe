Our marketing team is planning a new promotion for our bestselling fitness products. We need to analyze the current performance of our top-selling items and their related promotions to optimize our strategy.

**Task Requirements:**

1. If need to login, login with username 'admin' and password 'admin1234'

2. Start by checking our current bestsellers:
   - Identify the top 3 bestselling products based on their Price	and Quantity - record their names, prices, and quantities sold
   - Note the total Revenue amount displayed
   - Check if any of these bestsellers appear in the Top Search Terms table - if yes, record the search term and its usage count, else output 'No:0'

3. Investigate these bestselling products in detail:
   - For each of the top 3 bestsellers identified, search for them by name and record:
     - Their SKU
     - Current inventory quantity
     - Whether they are 'Enabled' or 'Disabled'

4. Check if we have existing promotions for these products:
   - Look for any active rules that might apply to fitness/yoga products
   - Find if there's a rule offering percentage discount - record the rule name and discount percentage
   - Count total number of active rules

5. Analyze customer purchasing patterns:
   - Count total number of orders in the system
   - Note the ID of the most recent order

6. Review our top customers who might be interested:
   - Find the customer who appears in the Last Orders section of the dashboard with the highest total
   - Look up this customer in the All Customers list and record his email and customer group
   - Count how many other customers are in the same group

7. Compile your findings and output them in the following exact format:

```
<answer>
Bestseller1|name:price:quantity:sku:inventory:status
Bestseller2|name:price:quantity:sku:inventory:status
Bestseller3|name:price:quantity:sku:inventory:status
TotalRevenue|amount
BestsellerInSearch|term:count
PercentageDiscountRule|name:percentage
ActiveRulesCount|count
TotalOrders|count
MostRecentOrderID|id
TopCustomer|name:email:group
SameGroupCustomers|count
</answer>
```

**Example Output:**
```
<answer>
Bestseller1|Product Name:$XX.XX:X:XXX(SKU):X:Enabled/Disabled
Bestseller2|Product Name:$XX.XX:X:XXX(SKU):X:Enabled/Disabled
Bestseller3|Product Name:$XX.XX:X:XXX(SKU):X:Enabled/Disabled
TotalRevenue|$XX.XX
BestsellerInSearch|Term:X or None:0
PercentageDiscountRule|Rule Name:XX%
ActiveRulesCount|X
TotalOrders|X
MostRecentOrderID|X or None
TopCustomer|Customer Name:email@example.com:Group Name
SameGroupCustomers|X
</answer>
```

