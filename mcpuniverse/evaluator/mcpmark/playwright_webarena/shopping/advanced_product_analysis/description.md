

**Task Requirements:**

1. Search for products with 'Ginger' in the Product Name field and price range $50.00 to $100.00

2. Add Q Mixers Premium Ginger Ale product to the comparison list

3. Find Intel NUC Kit product in Electronics category and add it to the comparison list

4. From the comparison page:
   - Record SKU numbers for both products
   - Add all products to cart

5. Record the total cart value

6. On the Ginger Ale product detail page, record:
   - Number of customer reviews
   - Name of the most recent reviewer (on top of the first page)

7. Output your findings in this format:

```
<answer>
GingerAleSKU|sku
IntelNUCSKU|sku
CartTotal|amount
ReviewCount|count
LatestReviewer|name
</answer>
```

**Example Output:**
```
<answer>
GingerAleSKU|XXXXXXXXX
IntelNUCSKU|XXXXXXXXX
CartTotal|$XXX.XX
ReviewCount|XX
LatestReviewer|name
</answer>
```

