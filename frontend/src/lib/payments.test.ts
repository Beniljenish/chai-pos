import { describe, expect, it } from 'vitest';
import { HttpError, type Api } from './api';
import { checkoutUrl, explainOnline, orderFor } from './payments';

const order = { razorpay_order_id: 'order_1', amount_paise: 4000, method: 'upi', status: 'created' };

describe('orderFor', () => {
  it('syncs the bill and asks again once when the server does not have it yet', async () => {
    const calls: string[] = [];
    let synced = false;
    const api = {
      async post(path: string, body: unknown) {
        calls.push(`${path} ${JSON.stringify(body)}`);
        if (!synced) throw new HttpError(409, 'bill_not_on_server');
        return order;
      },
    } as unknown as Pick<Api, 'post'>;
    const got = await orderFor(api, async () => void (synced = true), 'b1', 'upi');
    expect(got).toEqual(order);
    expect(calls).toEqual(Array(2).fill('/payments/razorpay/order {"bill_id":"b1","method":"upi"}'));
  });

  it('does not retry other refusals', async () => {
    let n = 0;
    const api = {
      async post() {
        n++;
        throw new HttpError(409, 'already_paid');
      },
    } as unknown as Pick<Api, 'post'>;
    let synced = 0;
    await expect(orderFor(api, async () => void synced++, 'b1', 'card')).rejects.toBeInstanceOf(HttpError);
    expect([n, synced]).toEqual([1, 0]);
  });
});

describe('checkout page and messages', () => {
  it('builds the checkout address on the API', () => {
    expect(checkoutUrl('https://api.example/api/v1/', 'order_A&B')).toBe(
      'https://api.example/api/v1/payments/razorpay/checkout?order_id=order_A%26B',
    );
  });
  it('explains refusals in shop words', () => {
    expect(explainOnline(new HttpError(409, 'already_paid'))).toBe('This bill is already paid.');
    expect(explainOnline(new Error('offline'))).toMatch(/needs internet/);
  });
});
