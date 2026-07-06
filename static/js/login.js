const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });

tl.to('[data-anim="card"]',  { opacity: 1, duration: 0.7 }, 0)
  .from('[data-anim="card"]', { y: 24, scale: 0.96, duration: 0.7 }, 0)

  .to('[data-anim="logo"]',  { opacity: 1, duration: 0.5, ease: 'back.out(1.7)' }, 0.35)
  .from('[data-anim="logo"]', { scale: 0.5, duration: 0.5, ease: 'back.out(1.7)' }, 0.35)

  .to('[data-anim="title"]',  { opacity: 1, duration: 0.4 }, 0.55)
  .from('[data-anim="title"]', { y: 12, duration: 0.4 }, 0.55)

  .to('[data-anim="field"]',  { opacity: 1, duration: 0.45, stagger: 0.09 }, 0.7)
  .from('[data-anim="field"]', { y: 16, duration: 0.45, stagger: 0.09 }, 0.7)

  .to('[data-anim="button"]',  { opacity: 1, duration: 0.5, ease: 'back.out(1.4)' }, 1.0)
  .from('[data-anim="button"]', { y: 16, scale: 0.94, duration: 0.5, ease: 'back.out(1.4)' }, 1.0);

if (document.querySelector('[data-anim="error"]')) {
    tl.to('[data-anim="error"]',  { opacity: 1, duration: 0.3 }, 0.2)
      .from('[data-anim="error"]', { x: -8, duration: 0.3 }, 0.2);
}
