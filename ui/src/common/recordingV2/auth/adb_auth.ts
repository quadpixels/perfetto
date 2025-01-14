// Copyright (C) 2022 The Android Open Source Project
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import {BigInteger, RSAKey} from 'jsbn-rsa';

import {assertExists, assertTrue} from '../../../base/logging';
import {
  base64Decode,
  base64Encode,
  hexEncode
} from '../../../base/string_utils';

const WORD_SIZE = 4;
const MODULUS_SIZE_BITS = 2048;
const MODULUS_SIZE = MODULUS_SIZE_BITS / 8;
const MODULUS_SIZE_WORDS = MODULUS_SIZE / WORD_SIZE;
const PUBKEY_ENCODED_SIZE = 3 * WORD_SIZE + 2 * MODULUS_SIZE;
const ADB_WEB_CRYPTO_ALGORITHM = {
  name: 'RSASSA-PKCS1-v1_5',
  hash: {name: 'SHA-1'},
  publicExponent: new Uint8Array([0x01, 0x00, 0x01]),  // 65537
  modulusLength: MODULUS_SIZE_BITS
};

const ADB_WEB_CRYPTO_EXPORTABLE = true;
const ADB_WEB_CRYPTO_OPERATIONS: KeyUsage[] = ['sign'];

const SIGNING_ASN1_PREFIX = [
  0x00,
  0x30,
  0x21,
  0x30,
  0x09,
  0x06,
  0x05,
  0x2B,
  0x0E,
  0x03,
  0x02,
  0x1A,
  0x05,
  0x00,
  0x04,
  0x14
];

const R32 = BigInteger.ONE.shiftLeft(32);  // 1 << 32

// Convert a BigInteger to an array of a specified size in bytes.
function bigIntToFixedByteArray(bn: BigInteger, size: number): Uint8Array {
  const paddedBnBytes = bn.toByteArray();
  let firstNonZeroIndex = 0;
  while (firstNonZeroIndex < paddedBnBytes.length &&
         paddedBnBytes[firstNonZeroIndex] === 0) {
    firstNonZeroIndex++;
  }
  const bnBytes = Uint8Array.from(paddedBnBytes.slice(firstNonZeroIndex));
  const res = new Uint8Array(size);
  assertTrue(bnBytes.length <= res.length);
  res.set(bnBytes, res.length - bnBytes.length);
  return res;
}

// Construct the public key that we will send to the device.
function serializeToAdbPublicKeyFormat(key: RSAKey): string {
  const n0inv = R32.subtract(key.n.modInverse(R32)).intValue();
  const r = BigInteger.ONE.shiftLeft(1).pow(MODULUS_SIZE_BITS);
  const rr = r.multiply(r).mod(key.n);

  const buffer = new ArrayBuffer(PUBKEY_ENCODED_SIZE);
  const dv = new DataView(buffer);
  dv.setUint32(0, MODULUS_SIZE_WORDS, true);
  dv.setUint32(WORD_SIZE, n0inv, true);

  const dvU8 = new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
  dvU8.set(
      bigIntToFixedByteArray(key.n, MODULUS_SIZE).reverse(), 2 * WORD_SIZE);
  dvU8.set(
      bigIntToFixedByteArray(rr, MODULUS_SIZE).reverse(),
      2 * WORD_SIZE + MODULUS_SIZE);

  dv.setUint32(2 * WORD_SIZE + 2 * MODULUS_SIZE, key.e, true);
  return base64Encode(new Uint8Array(buffer)) + ' perfetto.dev';
}

// Returns a new RSA key which:
// - contains the private key used for the signing
// - can be used to generate the public key format required by Adb
async function generateNewKeyPair(): Promise<RSAKey> {
  const keypair: CryptoKeyPair = await crypto.subtle.generateKey(
      ADB_WEB_CRYPTO_ALGORITHM,
      ADB_WEB_CRYPTO_EXPORTABLE,
      ADB_WEB_CRYPTO_OPERATIONS);
  const jwkPrivate = await crypto.subtle.exportKey('jwk', keypair.privateKey);
  const rsaKey = new RSAKey();
  rsaKey.setPrivateEx(
      hexEncode(base64Decode((assertExists(jwkPrivate.n)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.e)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.d)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.p)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.q)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.dp)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.dq)))),
      hexEncode(base64Decode((assertExists(jwkPrivate.qi)))));

  return rsaKey;
}

export class AdbKey {
  private rsaKey: RSAKey;

  private constructor(rsaKey: RSAKey) {
    this.rsaKey = rsaKey;
  }

  static async GenerateNewKeyPair(): Promise<AdbKey> {
    return new AdbKey(await generateNewKeyPair());
  }

  // Perform an RSA signing operation for the ADB auth challenge.
  //
  // For the RSA signature, the token is expected to have already
  // had the SHA-1 message digest applied.
  //
  // However, the adb token we receive from the device is made up of 20 randomly
  // generated bytes that are treated like a SHA-1. Therefore, we need to update
  // the message format.
  sign(token: Uint8Array): Uint8Array {
    const key = this.rsaKey;
    assertTrue(key.n.bitLength() === MODULUS_SIZE_BITS);

    // Message Layout (size equals that of the key modulus):
    // 00 01 FF FF FF FF ... FF [ASN.1 PREFIX] [TOKEN]
    const message = new Uint8Array(MODULUS_SIZE);

    // Initially fill the buffer with the padding
    message.fill(0xFF);

    // add prefix
    message[0] = 0x00;
    message[1] = 0x01;

    // add the ASN.1 prefix
    message.set(
        SIGNING_ASN1_PREFIX,
        message.length - SIGNING_ASN1_PREFIX.length - token.length);

    // then the actual token at the end
    message.set(token, message.length - token.length);

    const messageInteger = new BigInteger(Array.from(message));
    const signature = key.doPrivate(messageInteger);
    return new Uint8Array(bigIntToFixedByteArray(signature, MODULUS_SIZE));
  }

  getPublicKey(): string {
    return serializeToAdbPublicKeyFormat(this.rsaKey);
  }
}
