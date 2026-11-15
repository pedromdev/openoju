import { Routes } from '@angular/router';
import { authGuard, guestGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'videos' },
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () =>
      import('./features/auth/login-page').then((m) => m.LoginPage),
  },
  {
    path: 'setup',
    loadComponent: () =>
      import('./features/auth/setup-page').then((m) => m.SetupPage),
  },
  {
    path: 'invite',
    loadComponent: () =>
      import('./features/auth/invite-page').then((m) => m.InvitePage),
  },
  {
    path: 'privacy/:slug',
    loadComponent: () =>
      import('./features/privacy/public-privacy-page').then(
        (m) => m.PublicPrivacyPage,
      ),
  },
  {
    path: 'organizations',
    loadComponent: () =>
      import('./features/auth/organizations-page').then(
        (m) => m.OrganizationsPage,
      ),
  },
  {
    path: 'videos',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/videos/video-list-page').then((m) => m.VideoListPage),
  },
  {
    path: 'videos/:id',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/videos/video-detail-page').then(
        (m) => m.VideoDetailPage,
      ),
  },
  {
    path: 'profiles',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/profiles/profiles-page').then((m) => m.ProfilesPage),
  },
  {
    path: 'admin',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/admin/admin-page').then((m) => m.AdminPage),
  },
  { path: '**', redirectTo: 'videos' },
];
