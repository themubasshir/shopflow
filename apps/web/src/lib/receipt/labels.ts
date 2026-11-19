const en = {
  heading: "Sales receipt", invoice: "Invoice", time: "Date & time", counter: "Counter",
  cashier: "Cashier", customer: "Customer", trade_license: "Trade license", tax_registration: "Tax ID",
  items: "Items", amount: "Amount", line_discount: "Line discount", batch: "Batch", expiry: "Expiry",
  subtotal: "Subtotal", discount: "Discounts", loyalty_discount: "Loyalty discount", tax: "Tax",
  total: "Total payable", tender: "Payments", paid: "Total collected", due: "Outstanding due",
  points_redeemed: "Points redeemed", points_earned: "Points earned", points_balance: "Closing points",
  return_policy: "Return policy", voided: "VOIDED", refunded: "REFUNDED", voided_at: "Voided at",
  legacy: "Legacy receipt · available details preserved at migration",
  unavailable: "Legacy receipt · sale-time branding unavailable",
  cash: "Cash", bkash: "bKash", nagad: "Nagad", card: "Card",
};

const bn: typeof en = {
  heading: "বিক্রয় রসিদ", invoice: "চালান", time: "তারিখ ও সময়", counter: "কাউন্টার",
  cashier: "ক্যাশিয়ার", customer: "গ্রাহক", trade_license: "ট্রেড লাইসেন্স", tax_registration: "কর নিবন্ধন",
  items: "পণ্য", amount: "টাকা", line_discount: "পণ্যের ছাড়", batch: "ব্যাচ", expiry: "মেয়াদ",
  subtotal: "উপমোট", discount: "ছাড়", loyalty_discount: "লয়্যালটি ছাড়", tax: "কর",
  total: "মোট মূল্য", tender: "পরিশোধ", paid: "মোট প্রাপ্তি", due: "মোট বাকি",
  points_redeemed: "ব্যবহৃত পয়েন্ট", points_earned: "অর্জিত পয়েন্ট", points_balance: "অবশিষ্ট পয়েন্ট",
  return_policy: "ফেরত নীতি", voided: "বাতিল", refunded: "ফেরত দেওয়া হয়েছে", voided_at: "বাতিলের সময়",
  legacy: "পুরোনো রসিদ · হালনাগাদের সময় সংরক্ষিত তথ্য",
  unavailable: "পুরোনো রসিদ · বিক্রয়ের সময়ের দোকানের তথ্য পাওয়া যায়নি",
  cash: "নগদ টাকা", bkash: "বিকাশ", nagad: "নগদ (Nagad)", card: "কার্ড",
};

export const receiptLabels = { en, bn };
