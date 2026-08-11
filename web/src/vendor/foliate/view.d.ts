/**
 * Typen voor de meegeleverde foliate-js. De bibliotheek is plain JS zonder
 * eigen declaraties; dit beschrijft alleen wat BookPal ervan gebruikt.
 *
 * `view.js` wordt vooral om zijn bijwerking geïmporteerd: het definieert het
 * custom element `<foliate-view>`. De vorm van dat element staat in
 * `EpubReader.tsx`, dicht bij het gebruik.
 */

export declare const makeBook: (file: Blob | File) => Promise<unknown>;
