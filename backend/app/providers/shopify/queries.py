"""Admin GraphQL queries used by the sync (read-only).

Page sizes are chosen to keep each query's requested cost well under
Shopify's 1,000-point single-query limit:
  * PRODUCTS: flat, 100/page.
  * VARIANTS: 50/page x 10 inventory levels.
  * ORDERS:   20/page x 40 line items; refunds are a plain list (cheap).
    Orders with more line items, and refund line items, are fetched with
    follow-up queries.
No customer fields are requested anywhere.
"""

PRODUCTS = """
query AtlasProducts($first: Int!, $after: String) {
  products(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title handle status vendor productType createdAt updatedAt
      featuredMedia { preview { image { url } } }
    }
  }
}
"""

VARIANTS = """
query AtlasVariants($first: Int!, $after: String) {
  productVariants(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title sku price compareAtPrice updatedAt
      product { id }
      inventoryItem {
        id tracked
        unitCost { amount currencyCode }
        inventoryLevels(first: 10) {
          nodes {
            location { id }
            quantities(names: ["available", "on_hand", "committed", "incoming"]) {
              name quantity
            }
          }
        }
      }
    }
  }
}
"""

LOCATIONS = """
query AtlasLocations($first: Int!, $after: String) {
  locations(first: $first, after: $after, includeInactive: true) {
    pageInfo { hasNextPage endCursor }
    nodes { id name isActive }
  }
}
"""

_MONEY = "shopMoney { amount currencyCode }"

ORDERS = f"""
query AtlasOrders($first: Int!, $after: String, $query: String) {{
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{
      id name createdAt processedAt updatedAt cancelledAt test
      currencyCode displayFinancialStatus sourceName
      subtotalPriceSet {{ {_MONEY} }}
      totalDiscountsSet {{ {_MONEY} }}
      totalShippingPriceSet {{ {_MONEY} }}
      totalTaxSet {{ {_MONEY} }}
      totalPriceSet {{ {_MONEY} }}
      totalRefundedSet {{ {_MONEY} }}
      lineItems(first: 40) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{
          id name sku quantity
          product {{ id }}
          variant {{ id }}
          originalUnitPriceSet {{ {_MONEY} }}
          originalTotalSet {{ {_MONEY} }}
          totalDiscountSet {{ {_MONEY} }}
        }}
      }}
      refunds(first: 20) {{
        id createdAt
        totalRefundedSet {{ {_MONEY} }}
      }}
    }}
  }}
}}
"""

ORDER_LINE_ITEMS = f"""
query AtlasOrderLineItems($id: ID!, $first: Int!, $after: String) {{
  order(id: $id) {{
    lineItems(first: $first, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        id name sku quantity
        product {{ id }}
        variant {{ id }}
        originalUnitPriceSet {{ {_MONEY} }}
        originalTotalSet {{ {_MONEY} }}
        totalDiscountSet {{ {_MONEY} }}
      }}
    }}
  }}
}}
"""

REFUND_LINE_ITEMS = f"""
query AtlasRefundLines($id: ID!, $first: Int!, $after: String) {{
  refund(id: $id) {{
    refundLineItems(first: $first, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        lineItem {{ id }}
        quantity
        subtotalSet {{ {_MONEY} }}
      }}
    }}
  }}
}}
"""
