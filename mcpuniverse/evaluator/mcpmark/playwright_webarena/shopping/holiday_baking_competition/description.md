

**Task Requirements:**

1. Search 'gingerbread', sort by price (high to low):
   - Add most expensive product to comparison list
   - Record SKU of second most expensive product

2. Search 'cookie' with price range $20.00-$40.00:
   - Find product with highest rating % and at least 5 reviews in the first 2 pages (if tied, choose lowest price)
   - Record SKU and rating %
   - Select "Cookies: Oatmeal Chocolate Chunk" flavor if required
   - Add to cart with quantity 2

3. Search 'chocolate', sort by price (low to high):
   - Find cheapest product with at least 1 review
   - Record price and review count
   - Select "Peanut Butter Flavor" if required
   - Add to cart with quantity 3

4. In cart:
   - Update cookie quantity from 2 to 5
   - Record cart subtotal and total items count

5. Search 'gingerbread', go to page 2:
   - Find third product on page 2
   - Record SKU, price, and manufacturer

**Output Format:**

```
<answer>
SecondGingerbreadSKU|sku
HighestRatedCookieSKURating|sku:rating%
CheapestChocolatePriceReviews|$price:reviews
CartSubtotalAfterUpdate|$amount
TotalCartItems|count
Page2ThirdProductSKUPrice|sku:$price
ProductManufacturer|manufacturer
</answer>
```

