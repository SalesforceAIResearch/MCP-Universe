

**Task Requirements:**

1. In Video Games category, count products with customer rating 70% or higher in the first 2 pages

2. Sort products by price (ascending) and identify the cheapest product that has customer reviews

3. Find product with SKU 'B07D6LSCXZ' (N64 Controller), add to cart with quantity 3

4. Add products with SKU 'B071DR5V1K' and 'B082LZ4451' to comparison list, then count total products on comparison page

5. In cart, update N64 Controller quantity to 5 and record the subtotal for this item

6. Proceed to checkout and fill shipping form:
   - Email: test.buyer@example.com
   - First Name: Alice
   - Last Name: Johnson
   - Street Address: 456 Oak Avenue
   - Country: United States
   - State/Province: California
   - City: San Francisco
   - Zip Code: 94102
   - Phone: 415-555-0123
   Then count available shipping methods

7. Output your findings in this format:

```
<answer>
Products70Plus|count
CheapestReviewedSKU|sku
CheapestReviewedPrice|price
ComparisonCount|count
N64Subtotal|amount
CheckoutEmail|test.buyer@example.com
ShippingState|California
ShippingMethods|count
</answer>
```

